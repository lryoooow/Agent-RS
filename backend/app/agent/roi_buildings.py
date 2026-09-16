"""Resolve and execute explicit ROI building requests without an LLM guessing a resource."""
from __future__ import annotations

import math
import re
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from app.agent.imagery_access import iter_user_imagery_metadata
from app.agent.imagery_selection import grid_resolution_m
from app.agent.prompting.scenarios import latest_user_text
from app.core.settings import get_settings
from app.schemas.chat import AnalysisROI, ChatRequest


class RoiBuildingRequest(BaseModel):
    roi: AnalysisROI | None = None
    active_imagery_id: str | None = None
    source: Literal['auto', 'current_map', 'selected_imagery'] = 'auto'


class BuildingCandidate(BaseModel):
    imagery_id: str
    filename: str
    bounds: list[float] | None = None
    resolution_m: float | None = None
    eligible: bool
    reason: str
    can_locate: bool = False
    rgb: dict[str, int] = {}


class BuildingReadiness(BaseModel):
    status: Literal['ready', 'choose_imagery', 'blocked', 'missing_roi']
    message: str
    imagery_id: str | None = None
    candidates: list[BuildingCandidate] = []
    resolution_limit_m: float
    source: Literal['current_map', 'selected_imagery'] = 'selected_imagery'


def direct_roi_target(request: ChatRequest) -> str | None:
    # Deliberately narrow: explanations, negations, quoted requests and multi-step
    # instructions retain the normal agent path. A named ROI with no box must NOT
    # fall through to full-image inference.
    text = latest_user_text(request.messages).strip().rstrip('。.!！ ')
    text = re.sub(r'^(?:请帮我|请|帮我|麻烦你|麻烦|现在|直接|立即)+', '', text)
    area = r'(?:当前影像的|这张影像的|影像的)?(?:当前)?(?:框选区域|框选范围|选区)(?:内|中)?(?:的)?'
    if re.fullmatch(rf'(?:(?:提取|分割|识别){area}建筑(?:物)?|(?:对|在)?{area}(?:进行)?(?:建筑(?:物)?(?:提取|分割|识别)|(?:提取|分割|识别)建筑(?:物)?))(?:一下|吧)?', text):
        return 'building'
    if re.fullmatch(rf'(?:对|在)?{area}(?:进行)?(?:地物|地物语义|土地覆盖)(?:分类|分割)(?:一下|吧)?', text):
        return 'all'
    return None


def is_direct_building_request(request: ChatRequest) -> bool:
    return direct_roi_target(request) is not None


def _candidate(imagery_id: str, meta: dict, roi: AnalysisROI, limit: float) -> BuildingCandidate:
    resolution = grid_resolution_m(meta)
    roles = meta.get('band_roles') or {}
    count = meta.get('band_count') or meta.get('bands') or 0
    count = count if isinstance(count,int) else 0
    rgb = {role: roles.get(role) for role in ('red', 'green', 'blue')}
    rgb_valid = (all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= count for v in rgb.values())
                 and len(set(rgb.values())) == 3 and not any(v in (meta.get('alpha_bands') or []) for v in rgb.values()))
    bounds = meta.get('bounds')
    valid_bounds = isinstance(bounds, (list, tuple)) and len(bounds) == 4 and all(isinstance(x, (float, int)) and math.isfinite(x) for x in bounds)
    valid_bounds = valid_bounds and bounds[0] < bounds[2] and bounds[1] < bounds[3]
    can_locate = bool(valid_bounds and resolution is not None and resolution <= limit and rgb_valid)
    reason = ''
    if roi.kind == 'geo':
        if not valid_bounds:
            reason = '缺少有效地理范围，不能确认是否覆盖选区'
        else:
            a,b,c,d = roi.bbox
            w,s,e,n = bounds
            if a >= e or c <= w or b >= n or d <= s:
                reason = '不覆盖当前选区'
            elif not (w <= a and s <= b and e >= c and n >= d):
                reason = '只覆盖部分选区，请在影像范围内重新框选'
    if not reason and resolution is None:
        reason = '缺少实际像元分辨率，暂不能确认模型适用性'
    if not reason and resolution > limit:
        reason = f'约 {resolution:.2f} 米/像元，超过当前 SAM3 建筑提取的 {limit:g} 米使用上限'
    if not reason and not rgb_valid:
        reason = '缺少有效红、绿、蓝波段定义，请先核对影像元数据'
    return BuildingCandidate(imagery_id=imagery_id, filename=str(meta.get('filename') or imagery_id),
        bounds=list(bounds) if valid_bounds else None, resolution_m=resolution, eligible=not reason,
        reason=reason or '覆盖选区，具备 SAM3 开放词汇分割所需的数据', can_locate=can_locate,
        rgb=rgb if rgb_valid else {})


async def building_readiness(request: RoiBuildingRequest, *, user_id: str | None) -> BuildingReadiness:
    limit = get_settings().sam3_max_resolution_m
    if request.roi is None:
        return BuildingReadiness(status='missing_roi', message='请先在地图或影像中框选要提取建筑的区域。', resolution_limit_m=limit)
    entries = await iter_user_imagery_metadata(user_id)
    if request.roi.kind == 'pixel':
        entries = [(i,m) for i,m in entries if i == request.active_imagery_id]
    candidates = [_candidate(i,m,request.roi,limit) for i,m in entries]
    eligible = [c for c in candidates if c.eligible]
    selected = next((c for c in candidates if c.imagery_id == request.active_imagery_id), None)
    if request.roi.kind == 'geo' and (request.source == 'current_map' or (request.source == 'auto' and not (selected and selected.eligible))):
        from app.services.map_roi import MapROIError, map_roi_plan
        try:
            plan = map_roi_plan(request.roi.bbox)
        except MapROIError as exc:
            return BuildingReadiness(status='blocked',message=str(exc),candidates=candidates,source='current_map',resolution_limit_m=limit)
        return BuildingReadiness(status='ready',message=f"将直接使用当前地图的卫星底图分析选区（RGB，采样约 {plan['sample_m']:.2f} 米/像元）。",
            candidates=candidates,source='current_map',resolution_limit_m=limit)
    resolved = selected if request.active_imagery_id else eligible[0] if len(eligible) == 1 else None
    status = 'blocked'
    if resolved and resolved.eligible:
        status, message = 'ready', f'将使用「{resolved.filename}」提取选区内的建筑。'
    elif request.active_imagery_id:
        message = f'当前影像{selected.reason}。' if selected else '当前影像不可用，请重新选择。'
        if eligible:
            message += '请在当前分析影像选择器中选择可用影像，或切换到当前地图卫星底图。'
    elif len(eligible) > 1:
        status, message = 'choose_imagery', '有多张影像适用于此选区，请选择一张后执行。'
    elif request.roi.kind == 'pixel':
        message = '像素选区必须绑定当前影像，请先选择影像。'
    else:
        message = '当前选区没有可用于建筑提取的影像。'
        coarse = [c for c in candidates if '使用上限' in c.reason]
        if coarse:
            message += f'覆盖此处的影像约 {coarse[0].resolution_m:.2f} 米/像元，无法用于当前建筑分割。'
        message += '可切换到当前地图卫星底图直接分析此选区，也可选择覆盖此处的高分辨率影像。'
    return BuildingReadiness(status=status, message=message, imagery_id=resolved.imagery_id if resolved and resolved.eligible else None,
        candidates=candidates, resolution_limit_m=limit)


async def direct_building_events(request: ChatRequest, *, user_id: str | None):
    from app.agent.engine import AutogenTurnOutput
    from app.agent.tool_execution import PrepareRejected, prepare_tool_call, run_prepared_tool
    from app.agent.types import AgentTrace

    from app.services.map_roi import MapROIError, import_map_roi
    target = direct_roi_target(request)
    task_label = 'SAM3 建筑实例提取' if target == 'building' else 'SAM3 开放词汇地物分割'
    trace = AgentTrace(enabled=True)
    common = dict(tool_name='segment_instances', agent_name='segmentation_agent', domain='segmentation_agent',
        domain_label=task_label, parent_run_id=uuid4().hex, child_run_id=uuid4().hex,
        execution_kind='tool', dispatch_kind='tool')
    yield 'status', trace.add('context_assembled', '正在检查选区内的可用影像')
    source = (request.metadata or {}).get('analysis_source','auto')
    if source not in {'auto','current_map','selected_imagery'}:
        source = 'auto'
    if re.search('当前影像|这张影像',latest_user_text(request.messages)):
        source = 'selected_imagery'
    readiness = await building_readiness(RoiBuildingRequest(roi=request.analysis_roi, source=source,
        active_imagery_id=(request.metadata or {}).get('active_imagery_id')), user_id=user_id)
    if readiness.status != 'ready':
        content = f'**本次{task_label}未执行。** ' + readiness.message
        options = [c for c in readiness.candidates if c.eligible]
        if options:
            content += '\n\n可用影像：\n' + '\n'.join(f'- {c.filename}（`{c.imagery_id}`）' for c in options)
        yield 'status', trace.add('final_answering', '需要合适的分析影像', error_code=readiness.status)
        yield 'final', AutogenTurnOutput(content=content, trace=trace, strategy='roi_building', route_reason='roi_preflight')
        return
    if readiness.source == 'current_map':
        acquisition = {**common,'tool_name':'map_roi_image','child_run_id':uuid4().hex}
        yield 'status', trace.add('tool_execution_started', '正在获取框选区域的地图影像', **acquisition)
        try:
            image_id,meta = await import_map_roi(request.analysis_roi.bbox,user_id=user_id)
        except MapROIError as exc:
            yield 'status', trace.add('tool_execution_failed','选区地图影像获取失败',error_code='map_image_unavailable',**acquisition)
            yield 'final', AutogenTurnOutput(content=str(exc),trace=trace,strategy='roi_building')
            return
        candidate = _candidate(image_id,meta,request.analysis_roi,readiness.resolution_limit_m)
        yield 'status', trace.add('tool_execution_completed','选区地图影像已就绪',imagery_id=image_id,**acquisition)
    else:
        candidate = next(c for c in readiness.candidates if c.imagery_id == readiness.imagery_id)
    roi = request.analysis_roi
    concepts = ['building'] if target == 'building' else ['building', 'forest', 'water', 'road', 'farmland']
    arguments = dict(imagery_id=candidate.imagery_id, concepts=concepts,
        **{role+'_band':band for role,band in candidate.rgb.items()})
    arguments.update(dict(bbox=roi.bbox, bbox_crs='EPSG:4326') if roi.kind == 'geo' else dict(pixel_bbox=roi.rel))
    prepared = await prepare_tool_call('segment_instances', arguments, user_id=user_id)
    if isinstance(prepared, PrepareRejected):
        yield 'status', trace.add('final_answering', f'{task_label}未执行', error_code=prepared.error_detail)
        yield 'final', AutogenTurnOutput(content=prepared.result.tool_context, trace=trace, strategy='roi_building')
        return
    common['imagery_id'] = candidate.imagery_id
    yield 'status', trace.add('tool_requested', f'已匹配分析影像，准备{task_label}', **common)
    yield 'status', trace.add('tool_execution_started', f'正在进行选区{task_label}', **common)
    result = await run_prepared_tool(prepared)
    yield 'status', trace.add('tool_execution_failed' if result.error else 'tool_execution_completed',
        f'{task_label}失败' if result.error else f'{task_label}完成', error_code=result.error, **common)
    if result.geospatial_result:
        yield 'status', trace.add('geospatial_result_ready', f'选区{task_label}结果已生成', **common)
    geo = result.geospatial_result
    if geo is not None and not isinstance(geo,dict):
        geo = geo.model_dump(exclude_none=True)
    if result.error:
        content = result.tool_context
    else:
        content = f'**选区{task_label}已完成。** 使用影像：{candidate.filename}（`{candidate.imagery_id}`）。结果已叠加到地图。'
        if target == 'building':
            content += f"\n\n识别到建筑实例：{int((geo or {}).get('counts', {}).get('building', 0)):,} 个。"
            if (geo or {}).get('area_m2') is not None:
                content += f" SAM3 掩膜估算面积：{geo['area_m2']:,.2f} 平方米。"
        if (geo or {}).get('mask_url'):
            content += f"\n\n[下载 SAM3 合并掩膜 GeoTIFF]({geo['mask_url']})"
        if (geo or {}).get('vector_url'):
            content += f" · [下载实例矢量 GeoJSON]({geo['vector_url']})"
        if readiness.source == 'current_map':
            content += '\n\n数据来源：当前地图卫星底图（Esri 及其影像提供方）；仅包含 RGB，拍摄日期及原始传感器分辨率未确认。'
        content += '\n\n结果来自 SAM3 开放词汇实例分割，目标数量、地物边界和面积需结合原始影像核查。'
    yield 'status', trace.add('final_answering', f'{task_label}处理完成')
    yield 'final', AutogenTurnOutput(content=content, trace=trace, active_imagery_id=candidate.imagery_id,
        geospatial_result=geo, tool_result=result.tool_result, used_tool=True, strategy='roi_building', route_reason='roi_direct')
