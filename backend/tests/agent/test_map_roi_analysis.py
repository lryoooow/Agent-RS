import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
import rasterio
from PIL import Image

from app.agent.roi_buildings import RoiBuildingRequest, building_readiness, direct_roi_target, direct_building_events
from app.agent.types import ToolRunResult
from app.schemas.chat import ChatRequest, AnalysisROI
from app.services.map_roi import MapROIError, map_roi_plan, _validate_image_url, _write_raster

BOX=[114.0486,24.9516,114.0562,24.9578]
OWNER='owner'
ID='abcdef123456'


@pytest.mark.parametrize('text,target',[
    ('提取框选区域内的建筑物。','building'),('请帮我提取框选区域的建筑','building'),
    ('对框选区域进行建筑物提取','building'),('框选区域提取建筑物','building'),
    ('请对框选区域进行地物分类。','all'),('请对当前影像的框选区域进行地物分类。','all'),
    ('不要提取框选区域内的建筑物',None),('如何提取框选区域内的建筑物？',None),
    ('提取框选区域内的建筑物，然后生成报告',None),('解释“提取框选区域内的建筑物”',None),
    ('搜索框选区域的影像',None),('提取框选区域的建筑和农田',None),
])
def test_direct_requests_preserve_intent(text,target):
    assert direct_roi_target(ChatRequest(messages=[{'role':'user','content':text}]))==target


@pytest.mark.asyncio
async def test_map_does_not_require_uploaded_image(monkeypatch):
    inventory=AsyncMock(return_value=[])
    monkeypatch.setattr('app.agent.roi_buildings.iter_user_imagery_metadata',inventory)
    value=await building_readiness(RoiBuildingRequest(roi=AnalysisROI(kind='geo',bbox=BOX),source='current_map'),user_id=OWNER)
    assert value.status=='ready' and value.source=='current_map' and value.imagery_id is None


@pytest.mark.asyncio
async def test_explicit_coarse_image_does_not_silently_switch_source(monkeypatch):
    meta={'band_count':3,'band_roles':{'red':1,'green':2,'blue':3},'bounds':[112,23,115,26],
          'analysis_grid':{'crs':'EPSG:32649','pixel_size':[57.7,57.7]}}
    monkeypatch.setattr('app.agent.roi_buildings.iter_user_imagery_metadata',AsyncMock(return_value=[(ID,meta)]))
    result=await building_readiness(RoiBuildingRequest(roi=AnalysisROI(kind='geo',bbox=BOX),active_imagery_id=ID,source='selected_imagery'),user_id=OWNER)
    assert result.status=='blocked' and '57.70' in result.message


def test_plan_limits_and_export_url():
    plan=map_roi_plan(BOX)
    assert 16 < min(plan['width'],plan['height']) <= max(plan['width'],plan['height']) <= 2048
    assert .4 < plan['sample_m'] < .7
    for bbox in [[-180,-80,180,80],[114,24,114,25],[114,86,115,87]]:
        with pytest.raises(MapROIError): map_roi_plan(bbox)
    for url in ['http://127.0.0.1/internal','https://server.arcgisonline.com.evil.invalid/a',
                'https://server.arcgisonline.com/other.png','https://user@server.arcgisonline.com/arcgis/rest/directories/arcgisoutput/World_Imagery_MapServer/a.png']:
        with pytest.raises(MapROIError): _validate_image_url(url)


def test_export_extent_is_used_and_alpha_is_not_nir(tmp_path):
    bbox=[114.05,24.95,114.051,24.951]
    plan=map_roi_plan(bbox)
    plan['width'],plan['height']=64,64
    extent=dict(zip(('xmin','ymin','xmax','ymax'),plan['extent']))
    pixels=np.full((64,64,4),255,dtype='uint8');pixels[:,:,0]=30;pixels[:,:,1]=100;pixels[:,:,2]=170
    pixels[:4,:,3]=0
    stream=io.BytesIO();Image.fromarray(pixels).save(stream,format='PNG')
    meta=_write_raster(tmp_path,stream.getvalue(),{'width':64,'height':64,'extent':extent},plan)
    assert meta['band_roles']=={'red':1,'green':2,'blue':3} and meta['alpha_bands']==[4]
    assert meta['acquired_at'] is None and meta['native_resolution_m'] is None
    assert meta['source_origin']=='map_roi'
    assert meta['bounds'][0] <= bbox[0]+1e-5 and meta['bounds'][2] >= bbox[2]-1e-5
    with rasterio.open(tmp_path/'working.tif') as src:
        assert src.crs.to_epsg()==32650
        assert src.count==4 and src.colorinterp[-1].name=='alpha'
        assert src.read(1)[32,32] < src.read(2)[32,32] < src.read(3)[32,32]
        assert (src.read(4)==0).any()
    from app.agent.tools.roi_crop import crop_to_roi
    crop=crop_to_roi(tmp_path/'working.tif',tmp_path,bbox=bbox,bbox_crs='EPSG:4326',pixel_bbox=None)
    with rasterio.open(crop.path) as src:
        assert src.colorinterp[-1].name=='alpha'
        valid=src.dataset_mask()>0
        assert not valid.all() and valid.any()


@pytest.mark.asyncio
async def test_missing_box_never_runs_full_image(monkeypatch):
    run=AsyncMock(side_effect=AssertionError('must not infer'))
    monkeypatch.setattr('app.agent.tool_execution.run_prepared_tool',run)
    req=ChatRequest(messages=[{'role':'user','content':'提取框选区域内的建筑物。'}])
    events=[event async for event in direct_building_events(req,user_id=OWNER)]
    assert '先' in events[-1][1].content and not events[-1][1].used_tool
    run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('target,text', [('building','提取框选区域内的建筑物。'),('all','请对框选区域进行地物分类。')])
async def test_map_acquisition_then_inference_keeps_exact_roi(monkeypatch,target,text):
    meta={'filename':'map.tif','bounds':BOX,'band_count':4,'band_roles':{'red':1,'green':2,'blue':3},
          'alpha_bands':[4],'analysis_grid':{'crs':'EPSG:32650','pixel_size':[.6,.6]}}
    acquire=AsyncMock(return_value=(ID,meta))
    prepare=AsyncMock(return_value=SimpleNamespace(name='segment_instances'))
    geo={'type':'instance_segmentation','imagery_id':ID,'result_url':'/overlay.png','bounds':BOX,
         'concepts':['building'],'instance_count':2,'counts':{'building':2},'area_m2':.72,
         'mask_url':'/mask.tif','vector_url':'/instances.geojson'}
    run=AsyncMock(return_value=ToolRunResult(tool_context='ok',geospatial_result=geo))
    monkeypatch.setattr('app.agent.roi_buildings.iter_user_imagery_metadata',AsyncMock(return_value=[]))
    monkeypatch.setattr('app.services.map_roi.import_map_roi',acquire)
    monkeypatch.setattr('app.agent.tool_execution.prepare_tool_call',prepare)
    monkeypatch.setattr('app.agent.tool_execution.run_prepared_tool',run)
    req=ChatRequest(messages=[{'role':'user','content':text}],
        analysis_roi={'kind':'geo','bbox':BOX},metadata={'analysis_source':'current_map','active_imagery_id':None})
    events=[event async for event in direct_building_events(req,user_id=OWNER)]
    arguments=prepare.await_args.args[1]
    assert list(arguments['bbox'])==BOX and arguments['imagery_id']==ID
    assert arguments['concepts']==(['building'] if target=='building' else ['building','forest','water','road','farmland'])
    assert [arguments[f'{c}_band'] for c in ['red','green','blue']]==[1,2,3]
    final=events[-1][1]
    assert final.geospatial_result==geo and final.active_imagery_id==ID and final.used_tool
    if target=='building':
        assert '0.72' in final.content and '/mask.tif' in final.content and '/instances.geojson' in final.content
    else:
        assert '/mask.tif' in final.content
    stages=[(value.stage,value.metadata.get('tool_name')) for kind,value in events if kind=='status']
    assert stages.index(('tool_execution_completed','map_roi_image')) < stages.index(('tool_execution_started','segment_instances'))


@pytest.mark.asyncio
async def test_download_failure_never_runs_model(monkeypatch):
    monkeypatch.setattr('app.agent.roi_buildings.iter_user_imagery_metadata',AsyncMock(return_value=[]))
    monkeypatch.setattr('app.services.map_roi.import_map_roi',AsyncMock(side_effect=MapROIError('地图影像获取失败')))
    run=AsyncMock()
    monkeypatch.setattr('app.agent.tool_execution.run_prepared_tool',run)
    req=ChatRequest(messages=[{'role':'user','content':'提取框选区域内的建筑物。'}],analysis_roi={'kind':'geo','bbox':BOX})
    events=[event async for event in direct_building_events(req,user_id=OWNER)]
    assert '获取失败' in events[-1][1].content and not events[-1][1].geospatial_result
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_general_agent_prepares_map_then_binds_real_image(monkeypatch):
    from app.agent.engine.input import build_turn_input
    from app.agent.engine.turn_context import turn_scope, ToolInvocation
    from app.agent.engine.tools import RemoteSensingTool
    from app.agent.tool_registry import TOOLS
    from app.agent.tools.instance_segment.schema import InstanceSegmentArguments
    from autogen_core import CancellationToken
    monkeypatch.setattr('app.agent.engine.input.build_provider_request_context',
                        AsyncMock(return_value=SimpleNamespace(messages=[],has_imagery=False)))
    req=ChatRequest(messages=[{'role':'user','content':'提取框选区域内的建筑物，然后生成报告'}],
        analysis_roi={'kind':'geo','bbox':BOX},metadata={'active_imagery_id':None,'analysis_source':'current_map'})
    turn=await build_turn_input(req,user_id=OWNER)
    assert not any('未选中分析影像' in message.content for message in turn.initial_messages)
    assert turn.trusted_tool_arguments['prepare_map_roi']=={'bbox':BOX}
    prepare=AsyncMock()
    monkeypatch.setattr('app.agent.engine.tools.prepare_tool_call',prepare)
    with turn_scope(trusted_tool_arguments=turn.trusted_tool_arguments) as state:
        wrapper=RemoteSensingTool(TOOLS['segment_instances'])
        reply=await wrapper.run(InstanceSegmentArguments(imagery_id='000000000000',concepts=['building']),CancellationToken())
        assert 'prepare_map_roi' in reply and state.gpu_calls==0
        prepare.assert_not_awaited()
        state.record(ToolInvocation(name='prepare_map_roi',arguments={'bbox':BOX},result=ToolRunResult(
            tool_context='ok',geospatial_result={'imagery_id':ID},metadata={'band_roles':{'red':1,'green':2,'blue':3}})))
        args=state.arguments_for('segment_instances',{'imagery_id':'000000000000','concepts':['building'],'red_band':3,'green_band':2,'blue_band':1})
        assert args['imagery_id']==ID and [args[r+'_band'] for r in ['red','green','blue']]==[1,2,3]
        assert args['bbox']==BOX and state.latest_imported_imagery_id()==ID


@pytest.mark.asyncio
async def test_shared_map_tool_returns_provenance_and_imported_id(monkeypatch):
    from app.agent.tools.map_roi import MapROIArguments,run_map_roi
    acquire=AsyncMock(return_value=(ID,{'preview_url':'/preview.png','bounds':BOX}))
    monkeypatch.setattr('app.agent.tools.map_roi.import_map_roi',acquire)
    monkeypatch.setattr('app.agent.tools.map_roi.peek_current_user_id',lambda: OWNER)
    result=await run_map_roi(MapROIArguments(bbox=BOX))
    assert not result.error and result.geospatial_result['imagery_id']==ID
    assert result.metadata['band_roles']=={'red':1,'green':2,'blue':3}
    assert '原始传感器分辨率未知' in result.tool_context
    assert acquire.await_args.kwargs['user_id']==OWNER


@pytest.mark.asyncio
async def test_search_is_not_forced_into_map_analysis(monkeypatch):
    from app.agent.engine.input import build_turn_input
    monkeypatch.setattr('app.agent.engine.input.build_provider_request_context',
                        AsyncMock(return_value=SimpleNamespace(messages=[],has_imagery=False)))
    req=ChatRequest(messages=[{'role':'user','content':'搜索框选区域的 Sentinel-2 影像'}],
        analysis_roi={'kind':'geo','bbox':BOX},metadata={'active_imagery_id':None,'analysis_source':'current_map'})
    turn=await build_turn_input(req,user_id=OWNER)
    assert 'imagery_id' not in turn.trusted_tool_arguments['segment_instances']
    assert any('search_imagery' in message.content for message in turn.initial_messages)
    assert direct_roi_target(req) is None
