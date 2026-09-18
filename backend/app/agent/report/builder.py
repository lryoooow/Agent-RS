"""对话分析报告生成器（Word/.docx）。

对话工具 generate_report 与 HTTP 端点 /api/reports 共用此模块：
读取本对话**真实持久化**的分析结果（list_recent_analysis_results）+ 影像元信息，
用 python-docx 写成可下载的 .docx，落到该影像的 results 目录、复用既有下载路由。

硬约束：报告内容只来自真实结果，无结果即抛 ReportError 拒绝生成、绝不编造（延续
助手"不杜撰数据"的正确行为，并满足项目约束"影像分析结论必须标注数据来源与时间"）。
"""
from __future__ import annotations

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.agent.imagery_access import read_imagery_metadata
from app.core.paths import imagery_root
from app.db.pool import fetch_optional_pool
from app.db.repositories.conversation import get_conversation
from app.db.repositories.message import list_recent_analysis_results

logger = logging.getLogger(__name__)

REPORT_ANALYSIS_LIMIT = 20

REPORTABLE_GEOSPATIAL_TYPES = {
    "instance_segmentation",
    "segmentation",  # 只用于读取升级前已经持久化的历史结果
    "detection",
    "ndvi",
    "spectral_index",
    "water_mask",
    "cloud_mask",
    "composite",
    "ocr",
    "clip_reproject",
}


class ReportError(Exception):
    """报告无法生成（无持久化结果、非属主、存储不可用等）。文案对用户安全，不含内部细节。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReportArtifact:
    imagery_id: str
    filename: str
    download_url: str


async def build_conversation_report(
    *,
    conversation_id: str | None,
    user_id: str | None,
    imagery_id: str | None = None,
    current_analyses: list[dict[str, Any]] | None = None,
) -> ReportArtifact:
    """读本对话真实分析结果，生成 .docx 报告，返回下载信息。

    流程：归属校验 → 取持久化分析结果 → 选定影像 → 读影像元信息 →
    （无结果即拒绝）→ to_thread 写 docx → 落 results 目录 → 返回 download_url。
    """
    if not user_id:
        raise ReportError("无法确认用户身份，无法生成报告。", code="no_user")
    if not conversation_id:
        raise ReportError("缺少对话上下文，无法定位要汇总的分析结果。", code="no_conversation")

    pool = await fetch_optional_pool()
    if pool is None:
        raise ReportError("存储未启用，无法读取分析结果生成报告。", code="storage_inactive")

    async with pool.acquire() as conn:
        if await get_conversation(conn, conversation_id, user_id) is None:
            # 非属主或对话不存在：拒绝，不泄漏他人结果。
            raise ReportError("未找到该对话或无权访问，无法生成报告。", code="conversation_forbidden")
        analyses = await list_recent_analysis_results(
            conn,
            conversation_id=conversation_id,
            user_id=user_id,
            limit=REPORT_ANALYSIS_LIMIT,
        )

    # Only the tool runner supplies current_analyses; HTTP callers cannot submit
    # analysis data. Validate conversation ownership before using either source.
    selected_id, selected_analyses = _select_imagery_analyses(
        [*analyses, *(current_analyses or [])], imagery_id
    )
    if not selected_analyses:
        # 没有任何真实分析结果可写——绝不编造空报告。
        raise ReportError(
            "本对话还没有可用于报告的真实分析结果，请先对影像执行分析（如地物分类、目标检测）。",
            code="no_analysis",
        )

    imagery_meta = read_imagery_metadata(selected_id) if selected_id else None
    generated_at = datetime.now(timezone.utc)
    results_dir = imagery_root() / selected_id / "results"

    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        filename = f"report_{generated_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.docx"
        output_path = results_dir / filename
        # docx 写入是同步 CPU/IO，offload 到线程，避免阻塞事件循环（与上传/解析一致）。
        await asyncio.to_thread(
            _render_report_docx,
            output_path,
            imagery_id=selected_id,
            imagery_meta=imagery_meta,
            analyses=selected_analyses,
            generated_at=generated_at,
        )
    except ReportError:
        raise
    except Exception as exc:
        logger.exception("Report generation failed: %s", exc)
        raise ReportError("报告生成失败，请稍后重试。", code="render_failed") from exc

    return ReportArtifact(
        imagery_id=selected_id,
        filename=filename,
        download_url=f"/api/imagery/{selected_id}/results/{filename}",
    )


def _select_imagery_analyses(
    analyses: list[dict[str, Any]],
    imagery_id: str | None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """从对话分析结果里选定一张影像及其全部结果。

    指定 imagery_id → 只取该影像；否则取**最近一次被分析的影像**（analyses 已按时间正序，
    取最后一条出现的 imagery_id）。返回 (影像ID, 该影像的分析结果列表)。
    """
    # Preview/report/composite cards are not numeric analyses. Split payloads so
    # an entry containing results from two images cannot attribute one to another.
    reportable = []
    for entry in analyses:
        for key, supported in (
            ("geospatial_result", REPORTABLE_GEOSPATIAL_TYPES),
            ("tool_result", {"raster_inspect"}),
        ):
            payload = entry.get(key)
            if isinstance(payload, dict) and payload.get("type") in supported and payload.get("imagery_id"):
                reportable.append({key: payload})

    def _imagery_of(entry: dict[str, Any]) -> str | None:
        for key in ("geospatial_result", "tool_result"):
            payload = entry.get(key)
            if isinstance(payload, dict) and payload.get("imagery_id"):
                return str(payload["imagery_id"])
        return None

    if imagery_id:
        target = imagery_id
    else:
        target = None
        for entry in reportable:  # 正序遍历，最后命中的即最近一张
            found = _imagery_of(entry)
            if found:
                target = found
    if not target:
        return None, []
    selected = [entry for entry in reportable if _imagery_of(entry) == target]
    return target, selected


def _render_report_docx(
    output_path: Path,
    *,
    imagery_id: str,
    imagery_meta: dict[str, Any] | None,
    analyses: list[dict[str, Any]],
    generated_at: datetime,
) -> None:
    """把真实结构化结果、产物预览和边界说明写成完整 Word 报告。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    document = Document()
    _configure_document(document)
    meta = imagery_meta or {}
    ts_text = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    findings = _summary_findings(analyses)

    title = document.add_heading("遥感影像综合分析报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run(f"影像 {imagery_id}    生成时间 {ts_text}")

    document.add_heading("报告摘要", level=1)
    opening = f"本报告汇总影像 {imagery_id} 在当前对话中已经完成的 {len(analyses)} 项有效分析。"
    if findings:
        opening += "核心结果包括：" + "；".join(findings[:3]) + "。"
    opening += "报告中的数值、图表和成果文件均来自平台实际保存的分析结果。"
    document.add_paragraph(opening)

    document.add_heading("一 影像与分析范围", level=1)
    info_rows = _imagery_info_rows(imagery_id, meta, analyses)
    _add_table(document, ("项目", "内容"), info_rows)

    figure_no = 0
    used_images: set[Path] = set()
    preview = _preview_image_path(imagery_id, meta)
    if preview:
        figure_no += 1
        _add_figure(document, preview, f"图 {figure_no} 原始影像预览")
        used_images.add(preview.resolve())

    document.add_heading("二 分析覆盖情况", level=1)
    document.add_paragraph("下表区分已经完成和尚未执行的分析。尚未执行的项目不在本报告中生成结论。")
    _add_table(document, ("分析方向", "状态", "结果数量"), _coverage_rows(analyses))

    document.add_heading("三 分析方法与结果", level=1)
    result_no = 0
    for entry in analyses:
        if not _render_analysis_entry(document, entry, result_no + 1):
            continue
        result_no += 1
        geo = entry.get("geospatial_result")
        if isinstance(geo, dict):
            image_path = _artifact_path(imagery_id, geo.get("result_url"), image_only=True)
            if image_path and image_path.resolve() not in used_images:
                figure_no += 1
                _add_figure(document, image_path, f"图 {figure_no} {_analysis_label(entry)}结果预览")
                used_images.add(image_path.resolve())
            elif geo.get("result_url"):
                document.add_paragraph("该项结果保留了成果文件，但当前未找到可嵌入 Word 的预览图片。")
    if result_no == 0:
        document.add_paragraph("无可呈现的结构化分析结果。")

    document.add_heading("四 综合分析", level=1)
    if findings:
        for finding in findings:
            document.add_paragraph(finding, style="List Bullet")
    else:
        document.add_paragraph("当前结果不足以形成进一步的综合判断。")
    document.add_paragraph(
        "不同分析项反映的是同一影像的不同属性。目标分割和检测描述模型识别对象，"
        "光谱指数及掩膜描述像素统计，二者不能在缺少实地样本时相互替代或直接作为测绘真值。"
    )

    document.add_heading("五 成果文件", level=1)
    artifact_rows = _artifact_rows(analyses)
    if artifact_rows:
        _add_table(document, ("分析项", "成果类型", "文件"), artifact_rows)
    else:
        document.add_paragraph("本次分析没有记录可下载的派生成果文件。")

    document.add_heading("六 质量与适用边界", level=1)
    for note in _quality_notes(analyses):
        document.add_paragraph(note, style="List Bullet")

    document.add_heading("七 数据来源", level=1)
    document.add_paragraph(
        "本报告所有数值均来自本对话中对上述影像实际执行并保存的工具计算结果，未做任何人工编造。"
        "结果图片来自对应分析任务生成的预览产物；影像档案来自平台保存的原始元数据。"
    )
    document.add_paragraph(f"影像 ID：{imagery_id}；报告生成时间：{ts_text}。")

    document.save(str(output_path))


def _render_analysis_entry(document, entry: dict[str, Any], no: int) -> bool:
    """渲染一条分析结果到文档；成功返回 True。"""
    geo = entry.get("geospatial_result")
    tool = entry.get("tool_result")
    if isinstance(geo, dict):
        geo_type = geo.get("type")
        if geo_type == "segmentation":
            _render_segmentation(document, geo, no)
            return True
        if geo_type == "instance_segmentation":
            _render_instance_segmentation(document, geo, no)
            return True
        if geo_type == "detection":
            _render_detection(document, geo, no)
            return True
        if geo_type in ("ndvi", "spectral_index"):
            _render_index(document, geo, no)
            return True
        if geo_type in ("water_mask", "cloud_mask"):
            _render_mask(document, geo, no)
            return True
        if geo_type == "composite":
            _render_composite(document, geo, no)
            return True
        if geo_type == "ocr":
            _render_ocr(document, geo, no)
            return True
        if geo_type == "clip_reproject":
            _render_clip_reproject(document, geo, no)
            return True
    if isinstance(tool, dict) and tool.get("type") == "raster_inspect":
        _render_raster_inspect(document, tool, no)
        return True
    return False


def _render_segmentation(document, geo: dict[str, Any], no: int) -> None:
    task = "建筑提取及四类统计" if geo.get("target_class") == "building" else "地物分类"
    document.add_heading(f"{no}. {task}（历史结果，旧格式）", level=2)
    classes = [c for c in (geo.get("classes") or []) if isinstance(c, dict)]
    if not classes:
        document.add_paragraph("未识别到地物类别。")
        return
    if geo.get("total_pixels") is not None:
        document.add_paragraph(f"分析有效像素数：{geo['total_pixels']}。统计基于分析网格，可能与原始影像尺寸不同。")
    has_area = any(isinstance(c.get("area_m2"), (int, float)) for c in classes)
    rows = []
    for item in classes:
        pct = item.get("percentage")
        row = [str(item.get("label") or item.get("name") or "未知"), str(item.get("pixel_count", "—")), f"{pct:.2f}%" if _number(pct) else "—"]
        if has_area:
            area = item.get("area_m2")
            row.append(_format_area(area) if _number(area) else "—")
        rows.append(tuple(row))
    headers = ("类别", "像素数", "占比", "面积") if has_area else ("类别", "像素数", "占比")
    _add_table(document, headers, rows)
    dominant = max(classes, key=lambda item: float(item.get("percentage") or -1))
    if _number(dominant.get("percentage")):
        document.add_paragraph(f"占比最高的类别为{dominant.get('label') or dominant.get('name')}，占 {dominant['percentage']:.2f}%。")


def _render_instance_segmentation(document, geo: dict[str, Any], no: int) -> None:
    document.add_heading(f"{no}. SAM3 开放词汇实例分割", level=2)
    document.add_paragraph(f"模型：{geo.get('model_name') or 'SAM3'}；实例总数：{int(geo.get('instance_count') or 0)}。")
    if isinstance(geo.get("union_pixels"), int):
        document.add_paragraph(f"合并掩膜像素数：{geo['union_pixels']}。")
    if _number(geo.get("area_m2")):
        document.add_paragraph(f"模型掩膜估算面积：{_format_area(geo['area_m2'])}。")
    counts = geo.get("counts") or {}
    if isinstance(counts, dict) and counts:
        _add_table(document, ("目标概念", "实例数"), [(str(concept), str(count)) for concept, count in counts.items()])
        dominant = max(counts.items(), key=lambda item: int(item[1] or 0))
        document.add_paragraph(f"实例数量最多的目标概念为 {dominant[0]}，共 {dominant[1]} 个。")
    document.add_paragraph("上述数量、轮廓与面积均为 SAM3 模型识别结果，需结合原始影像复核。")


def _render_detection(document, geo: dict[str, Any], no: int) -> None:
    document.add_heading(f"{no}. 目标检测（DOTA 15 类）", level=2)
    total = geo.get("detection_count")
    document.add_paragraph(f"检测目标总数：{total if total is not None else '未知'}")
    classes = [c for c in (geo.get("classes") or []) if isinstance(c, dict)]
    if not classes:
        return
    _add_table(document, ("类别", "数量"), [
        (str(item.get("label") or item.get("name") or "未知"), str(item.get("count", "—"))) for item in classes
    ])
    if _number(geo.get("score_threshold")):
        document.add_paragraph(f"结果采用置信度阈值 {geo['score_threshold']:.2f}。")


def _render_index(document, geo: dict[str, Any], no: int) -> None:
    stats = geo.get("stats") or {}
    index_type = geo.get("index_type") or stats.get("index_type") or ("NDVI" if geo.get("type") == "ndvi" else "光谱指数")
    document.add_heading(f"{no}. {index_type} 指数统计", level=2)
    rows = []
    for key, label in (("min", "最小值"), ("max", "最大值"), ("mean", "均值"), ("std", "标准差")):
        value = stats.get(key)
        if _number(value):
            rows.append((label, f"{value:.4g}"))
    if _number(stats.get("nodata_pct")):
        rows.append(("无效像素占比", f"{stats['nodata_pct']:.2f}%"))
    _add_table(document, ("统计量", "数值"), rows)
    interpretation = _index_interpretation(str(index_type), stats.get("mean"))
    if interpretation:
        document.add_paragraph(interpretation)


def _render_raster_inspect(document, tool: dict[str, Any], no: int) -> None:
    document.add_heading(f"{no}. 影像质检", level=2)
    bits = []
    if tool.get("width") and tool.get("height"):
        bits.append(f"分析网格尺寸 {tool['width']}×{tool['height']} px")
    if tool.get("band_count"):
        bits.append(f"{tool['band_count']} 波段")
    if tool.get("crs"):
        bits.append(f"CRS {tool['crs']}")
    document.add_paragraph("；".join(bits) if bits else "基本信息缺失。")
    rows = []
    for key, label in (("dtype", "数据类型"), ("pixel_size", "像元大小"), ("nodata", "NoData"), ("bounds", "原坐标系四至"), ("bounds_wgs84", "WGS84 四至"), ("center_wgs84", "WGS84 中心"), ("band_roles", "波段角色"), ("band_roles_source", "波段角色来源"), ("color_interpretations", "源颜色解释"), ("alpha_bands", "透明度波段"), ("source_grid", "原始网格"), ("analysis_grid", "分析网格"), ("resampled", "分析时已重采样"), ("alpha_statistics", "透明度波段统计")):
        value = tool.get(key)
        if value not in (None, "", [], {}):
            rows.append((label, _format_value(value)))
    capabilities = tool.get("capabilities") or {}
    if capabilities:
        rows.append(("波段能力", "、".join(
            f"{key.removeprefix('has_').upper()}={'可用' if value else '不可用'}"
            for key, value in capabilities.items()
        )))
    if rows:
        _add_table(document, ("质检项目", "结果"), rows)
    band_stats = [item for item in (tool.get("per_band_stats") or []) if isinstance(item, dict)]
    if band_stats:
        _add_table(document, ("波段", "最小值", "最大值", "均值", "标准差"), [
            (str(item.get("band", "—")), _fmt_number(item.get("min")), _fmt_number(item.get("max")), _fmt_number(item.get("mean")), _fmt_number(item.get("std")))
            for item in band_stats[:16]
        ])


def _render_mask(document, geo: dict[str, Any], no: int) -> None:
    water = geo.get("type") == "water_mask"
    document.add_heading(f"{no}. {'水体掩膜' if water else '云与阴影分析'}", level=2)
    stats = geo.get("stats") or {}
    labels = {
        "water_pct": "水体占比", "non_water_pct": "非水体占比", "ndwi_threshold": "NDWI 阈值",
        "cloud_pct": "云占比", "shadow_pct": "阴影占比", "clear_pct": "晴空占比", "nodata_pct": "无效像素占比",
    }
    rows = []
    for key, label in labels.items():
        value = stats.get(key)
        if _number(value):
            rows.append((label, f"{value:.2f}%" if key.endswith("_pct") else f"{value:.4g}"))
    _add_table(document, ("统计项", "数值"), rows)
    if water and _number(stats.get("water_pct")):
        document.add_paragraph(f"分析网格中模型判定为水体的像素占 {stats['water_pct']:.2f}%。")
    if not water and _number(stats.get("clear_pct")):
        document.add_paragraph(f"晴空像素占 {stats['clear_pct']:.2f}%，该比例可用于判断后续光谱分析的可用范围。")


def _render_composite(document, geo: dict[str, Any], no: int) -> None:
    modes = {"true_color": "真彩色", "false_color": "假彩色", "custom": "自定义波段"}
    mode = modes.get(str(geo.get("mode")), str(geo.get("mode") or "波段组合"))
    document.add_heading(f"{no}. {mode}预览", level=2)
    bands = geo.get("bands_used") or []
    document.add_paragraph(f"本预览使用波段：{', '.join(str(v) for v in bands) if bands else '未记录'}。")
    document.add_paragraph("波段组合用于目视判读和结果核验，不单独作为定量地物结论。")


def _render_ocr(document, geo: dict[str, Any], no: int) -> None:
    document.add_heading(f"{no}. 影像文字识别", level=2)
    stats = geo.get("stats") or {}
    rows = []
    for key, label in (("block_count", "文本块数量"), ("char_count", "字符数量"), ("avg_confidence", "平均置信度"), ("min_confidence_seen", "最低置信度"), ("grayscale", "灰度模式")):
        value = stats.get(key)
        if value is not None:
            rows.append((label, _format_value(value)))
    _add_table(document, ("识别项目", "结果"), rows)


def _render_clip_reproject(document, geo: dict[str, Any], no: int) -> None:
    document.add_heading(f"{no}. 裁剪与重投影", level=2)
    stats = geo.get("stats") or {}
    rows = []
    for key, label in (("src_crs", "源坐标系"), ("dst_crs", "目标坐标系"), ("width", "输出宽度"), ("height", "输出高度"), ("band_count", "波段数"), ("clipped", "已裁剪"), ("reprojected", "已重投影")):
        value = stats.get(key)
        if value is not None:
            rows.append((label, _format_value(value)))
    _add_table(document, ("处理项目", "结果"), rows)


def _configure_document(document) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    for section in document.sections:
        section.top_margin = Inches(0.72)
        section.bottom_margin = Inches(0.72)
        section.left_margin = Inches(0.78)
        section.right_margin = Inches(0.78)
    styles = document.styles
    for name, size in (("Normal", 10.5), ("Title", 22), ("Heading 1", 15), ("Heading 2", 12.5)):
        style = styles[name]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    styles["Normal"].paragraph_format.space_after = Pt(6)
    styles["Normal"].paragraph_format.line_spacing = 1.15
    document.core_properties.title = "遥感影像综合分析报告"
    document.core_properties.subject = "Agent-RS 影像分析结果"
    document.core_properties.author = "Agent-RS"


def _add_table(document, headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    if not rows:
        document.add_paragraph("未记录可用数据。")
        return
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = True
    header_cells = table.rows[0].cells
    for index, value in enumerate(headers):
        header_cells[index].text = value
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = str(value)
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tc_pr = cell._tc.get_or_add_tcPr()
            margins = tc_pr.first_child_found_in("w:tcMar")
            if margins is None:
                margins = OxmlElement("w:tcMar")
                tc_pr.append(margins)
            for edge in ("top", "left", "bottom", "right"):
                node = margins.find(qn(f"w:{edge}"))
                if node is None:
                    node = OxmlElement(f"w:{edge}")
                    margins.append(node)
                node.set(qn("w:w"), "90")
                node.set(qn("w:type"), "dxa")
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "1F4E78" if row_index == 0 else ("F2F6FA" if row_index % 2 == 0 else "FFFFFF"))
            tc_pr.append(shade)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                if row_index == 0:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    run.font.size = Pt(9.5)
                    if row_index == 0:
                        run.bold = True
                        run.font.color.rgb = RGBColor(255, 255, 255)
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    tr_pr.append(repeat)
    document.add_paragraph().paragraph_format.space_after = Pt(1)


def _add_figure(document, path: Path, caption: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt
    from PIL import Image

    try:
        with Image.open(path) as image:
            width_px, height_px = image.size
        if not width_px or not height_px:
            return
        aspect = width_px / height_px
        width = min(6.55, 5.05 * aspect)
        height = width / aspect
        if height > 5.05:
            height = 5.05
            width = height * aspect
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True
        paragraph.add_run().add_picture(str(path), width=Inches(width), height=Inches(height))
        cap = document.add_paragraph(caption)
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_after = Pt(8)
        run = cap.runs[0]
        run.italic = True
        run.font.size = Pt(9)
    except Exception:
        logger.warning("Report image could not be embedded: %s", path, exc_info=True)


def _preview_image_path(imagery_id: str, meta: dict[str, Any]) -> Path | None:
    path = _artifact_path(imagery_id, meta.get("preview_url"), image_only=True)
    if path:
        return path
    candidate = imagery_root() / imagery_id / "results" / "preview.png"
    return candidate if candidate.is_file() else None


def _artifact_path(imagery_id: str, value: Any, *, image_only: bool = False) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    name = Path(urlparse(value).path).name
    if not name or name in {".", ".."}:
        return None
    if image_only and Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return None
    root = (imagery_root() / imagery_id / "results").resolve()
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _imagery_info_rows(imagery_id: str, meta: dict[str, Any], analyses: list[dict[str, Any]]) -> list[tuple[str, str]]:
    inspect = next((entry.get("tool_result") for entry in reversed(analyses) if isinstance(entry.get("tool_result"), dict)), {}) or {}
    width = meta.get("width") or inspect.get("width")
    height = meta.get("height") or inspect.get("height")
    bounds = inspect.get("bounds_wgs84") or meta.get("bounds")
    roles = meta.get("band_roles") or inspect.get("band_roles")
    rows = [
        ("影像 ID", imagery_id),
        ("文件名", str(meta.get("filename") or "未记录")),
        ("传感器或卫星", str(meta.get("sensor") or meta.get("satellite") or "未记录")),
        ("获取时间", str(meta.get("datetime") or meta.get("acquired_at") or meta.get("created_at") or "未记录")),
        ("坐标系", str(meta.get("crs") or inspect.get("crs") or "未识别")),
        ("影像尺寸", f"{width} × {height} px" if width and height else "未记录"),
        ("波段数", str(meta.get("band_count") or inspect.get("band_count") or "未记录")),
        ("数据类型", str(meta.get("dtype") or inspect.get("dtype") or "未记录")),
        ("像元大小", _format_value(inspect.get("pixel_size") or meta.get("pixel_size") or "未记录")),
        ("地图范围", _format_value(bounds) if bounds else "未记录"),
        ("波段角色", _format_value(roles) if roles else "未确认"),
    ]
    return rows


def _coverage_rows(analyses: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    types = [_analysis_type(entry) for entry in analyses]
    groups = [
        ("影像质检", {"raster_inspect"}),
        ("SAM3 实例分割", {"instance_segmentation", "segmentation"}),
        ("目标检测", {"detection"}),
        ("光谱指数", {"ndvi", "spectral_index"}),
        ("水体分析", {"water_mask"}),
        ("云与阴影分析", {"cloud_mask"}),
        ("波段可视化", {"composite"}),
        ("文字识别", {"ocr"}),
        ("裁剪与重投影", {"clip_reproject"}),
    ]
    rows = []
    for label, accepted in groups:
        count = sum(item in accepted for item in types)
        rows.append((label, "已完成" if count else "未执行", str(count)))
    return rows


def _summary_findings(analyses: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    for entry in analyses:
        payload = entry.get("geospatial_result") or entry.get("tool_result") or {}
        result_type = payload.get("type")
        if result_type == "raster_inspect":
            text = []
            if payload.get("width") and payload.get("height"):
                text.append(f"分析网格 {payload['width']} × {payload['height']} px")
            if payload.get("band_count"):
                text.append(f"{payload['band_count']} 个波段")
            if payload.get("crs"):
                text.append(f"坐标系 {payload['crs']}")
            if text:
                findings.append("影像质检确认" + "，".join(text))
        elif result_type == "instance_segmentation":
            concepts = "、".join(str(v) for v in payload.get("concepts") or []) or "指定目标"
            text = f"SAM3 对{concepts}识别出 {int(payload.get('instance_count') or 0)} 个实例"
            if _number(payload.get("area_m2")):
                text += f"，合并掩膜面积约 {_format_area(payload['area_m2'])}"
            findings.append(text)
        elif result_type == "segmentation":
            classes = [item for item in payload.get("classes") or [] if isinstance(item, dict) and _number(item.get("percentage"))]
            if classes:
                dominant = max(classes, key=lambda item: item["percentage"])
                findings.append(f"历史分类结果中{dominant.get('label') or dominant.get('name')}占比最高，为 {dominant['percentage']:.2f}%")
        elif result_type == "detection":
            findings.append(f"目标检测共识别 {int(payload.get('detection_count') or 0)} 个目标")
        elif result_type in {"ndvi", "spectral_index"}:
            stats = payload.get("stats") or {}
            name = str(payload.get("index_type") or ("NDVI" if result_type == "ndvi" else "光谱指数")).upper()
            if _number(stats.get("mean")):
                findings.append(f"{name} 均值为 {stats['mean']:.4g}，范围 {_fmt_number(stats.get('min'))} 至 {_fmt_number(stats.get('max'))}")
        elif result_type == "water_mask":
            water = (payload.get("stats") or {}).get("water_pct")
            if _number(water):
                findings.append(f"水体掩膜判定水体像素占 {water:.2f}%")
        elif result_type == "cloud_mask":
            stats = payload.get("stats") or {}
            if _number(stats.get("clear_pct")):
                findings.append(f"云影分析判定晴空像素占 {stats['clear_pct']:.2f}%")
        elif result_type == "ocr":
            count = (payload.get("stats") or {}).get("block_count")
            if count is not None:
                findings.append(f"文字识别得到 {count} 个文本块")
    return list(dict.fromkeys(findings))


def _quality_notes(analyses: list[dict[str, Any]]) -> list[str]:
    types = {_analysis_type(entry) for entry in analyses}
    notes = ["报告只汇总已经成功执行并保存的分析；覆盖表中标记为未执行的项目没有推断结论。"]
    if types & {"instance_segmentation", "segmentation"}:
        notes.append("SAM3 及历史分类结果属于模型识别，目标数量、边界和面积需结合原始影像或抽样标注复核。")
    if "detection" in types:
        notes.append("目标检测结果受模型类别范围、目标尺度、遮挡和置信度阈值影响，不能替代人工清查。")
    if types & {"ndvi", "spectral_index", "water_mask", "cloud_mask"}:
        notes.append("光谱指数和像素掩膜受传感器波段、辐射定标、季节、大气和阈值影响；跨期比较前应统一处理口径。")
    notes.append("面积为影像像元或模型掩膜换算结果，不作为产权、测绘或法定统计面积。")
    return notes


def _artifact_rows(analyses: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    keys = (
        ("result_url", "结果预览"), ("mask_url", "合并掩膜 GeoTIFF"),
        ("instance_raster_url", "实例标签 GeoTIFF"), ("vector_url", "矢量 GeoJSON"),
        ("instances_url", "实例明细 JSON"), ("metrics_url", "指标 JSON"),
        ("detections_url", "检测明细 JSON"), ("download_url", "派生栅格"),
    )
    rows = []
    seen = set()
    for entry in analyses:
        payload = entry.get("geospatial_result")
        if not isinstance(payload, dict):
            continue
        for key, label in keys:
            value = payload.get(key)
            if not isinstance(value, str) or not value:
                continue
            filename = Path(urlparse(value).path).name
            marker = (key, filename)
            if marker in seen:
                continue
            seen.add(marker)
            rows.append((_analysis_label(entry), label, filename or value))
    return rows


def _analysis_type(entry: dict[str, Any]) -> str:
    payload = entry.get("geospatial_result") or entry.get("tool_result") or {}
    return str(payload.get("type") or "") if isinstance(payload, dict) else ""


def _analysis_label(entry: dict[str, Any]) -> str:
    labels = {
        "raster_inspect": "影像质检", "instance_segmentation": "SAM3 实例分割", "segmentation": "历史地物分类",
        "detection": "目标检测", "ndvi": "NDVI", "spectral_index": "光谱指数", "water_mask": "水体掩膜",
        "cloud_mask": "云与阴影", "composite": "波段组合", "ocr": "文字识别", "clip_reproject": "裁剪与重投影",
    }
    payload = entry.get("geospatial_result") or entry.get("tool_result") or {}
    if isinstance(payload, dict) and payload.get("type") == "spectral_index":
        return str(payload.get("index_type") or "光谱指数").upper()
    return labels.get(_analysis_type(entry), "分析结果")


def _index_interpretation(name: str, mean: Any) -> str | None:
    if not _number(mean) or name.upper() != "NDVI":
        return None
    value = float(mean)
    if value >= 0.6:
        level = "整体植被信号较强"
    elif value >= 0.3:
        level = "整体呈中等植被信号"
    elif value >= 0.1:
        level = "整体植被信号偏弱或地表类型混合"
    else:
        level = "整体以低植被信号或非植被像素为主"
    return f"按 NDVI 的通用相对判读，该影像均值为 {value:.3f}，{level}；具体地物仍需结合季节、传感器和现场信息确认。"


def _format_area(value: Any) -> str:
    area = float(value)
    if area >= 1_000_000:
        return f"{area:,.2f} 平方米（{area / 1_000_000:.3f} 平方公里）"
    if area >= 10_000:
        return f"{area:,.2f} 平方米（{area / 10_000:.3f} 公顷）"
    return f"{area:,.2f} 平方米"


def _fmt_number(value: Any) -> str:
    return f"{float(value):.4g}" if _number(value) else "—"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, dict):
        return "、".join(f"{key}={item}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt_number(item) if _number(item) else str(item) for item in value)
    return str(value)
