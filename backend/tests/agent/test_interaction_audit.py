from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from app.agent.imagery_selection import use_current_selection, geo_roi_mismatch, grid_resolution_m
from app.agent.rag.relevance import should_retrieve_documents, semantic_similarity
from app.agent.rag import service
from app.core.settings import get_settings

@pytest.mark.parametrize('query', ['提取建筑','这张影像提取建筑','当前影像质检'])
def test_current_image_binding_intent(query):
    assert use_current_selection(query)

@pytest.mark.parametrize('query', ['提取 fec6252c9325 的建筑','对上一张影像分类','对比两张影像','导入这张影像'])
def test_explicit_or_multi_image_request_not_overridden(query):
    assert not use_current_selection(query)

@pytest.mark.parametrize('query', ['对这张影像提取建筑','框选区域提取河流、道路、农田','地图在哪里','现在这张影像位置是哪里','重试','继续'])
def test_image_operations_do_not_trigger_documents(query):
    assert not should_retrieve_documents(query)

@pytest.mark.parametrize('query', ['根据文档提取建筑','灵瞰平台实施方案中的技术架构是什么','根据上传的文档，平台如何关联知识图谱和智能体','如何进行遥感影像分类'])
def test_document_and_method_questions_can_retrieve(query):
    assert should_retrieve_documents(query)

def test_relevance_uses_cosine_not_rrf_rank():
    assert semantic_similarity({'rrf_score': 1, 'vector_score': .44}, [1,0]) == .44
    assert semantic_similarity({'embedding': '[0,1]'}, [1,0]) == 0
    assert semantic_similarity({'embedding': [1,0]}, [1,0]) == 1
    assert semantic_similarity({'score': 1}, [1,0]) == -1

def test_actual_transcript_roi_does_not_cover_old_image():
    roi=[114.276528,25.109657,114.298709,25.127011]
    assert geo_roi_mismatch([114.180476,24.848556,114.229424,24.893026], roi)
    assert not geo_roi_mismatch([112.796265,23.483785,115.072828,25.607802], roi)
    assert grid_resolution_m({'analysis_grid': {'crs':'EPSG:32649','pixel_size':[57.694,57.697]}}) == 57.697

class Pool:
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass

@pytest.mark.asyncio
async def test_irrelevant_top_k_never_expands_or_calls_graph(monkeypatch):
    search=AsyncMock(return_value=[{'content':'unrelated implementation plan','vector_score':.44}])
    rerank=AsyncMock()
    monkeypatch.setattr(service,'get_rerank_service',lambda: SimpleNamespace(rerank=rerank))
    result=await service.retrieve_rag_context(Pool(),query='今天中午吃什么',embedding=[1,0],user_id='owner',trace={},search_fn=search)
    assert result.context is None and result.retrieved_chunks == 0
    assert result.trace['relevance_rejected'] == 1
    rerank.assert_not_called()

@pytest.mark.asyncio
async def test_direct_image_task_skips_embedding(monkeypatch):
    from app.agent.engine.memory.rag_memory import RagMemory
    monkeypatch.setenv('DATABASE_ENABLED','true'); get_settings.cache_clear()
    pool=AsyncMock(side_effect=AssertionError('must not access document DB'))
    monkeypatch.setattr('app.agent.engine.memory.rag_memory.fetch_optional_pool',pool)
    result=await RagMemory(user_id='owner').query('对这张影像提取建筑')
    assert not result.results
    pool.assert_not_called(); get_settings.cache_clear()

@pytest.mark.asyncio
async def test_framework_binds_selected_image_and_preserves_roi(monkeypatch):
    from app.agent.engine.input import build_turn_input
    from app.schemas.chat import ChatRequest
    monkeypatch.setattr('app.agent.engine.input.build_provider_request_context',AsyncMock(return_value=SimpleNamespace(messages=[])))
    monkeypatch.setattr('app.agent.engine.input.user_owns_imagery',AsyncMock(return_value=True))
    monkeypatch.setattr('app.agent.engine.input.get_user_imagery_metadata',AsyncMock(return_value=None))
    req=ChatRequest(messages=[{'role':'user','content':'这张影像提取建筑'}],metadata={'active_imagery_id':'4256dea5c68b'},analysis_roi={'kind':'geo','bbox':[114.27,25.10,114.30,25.13]})
    turn=await build_turn_input(req,user_id='owner')
    args=turn.trusted_tool_arguments['segment_instances']
    assert args['imagery_id']=='4256dea5c68b' and args['bbox']==[114.27,25.10,114.30,25.13]
    req.messages[0].content='提取 fec6252c9325 的建筑'
    turn=await build_turn_input(req,user_id='owner')
    assert 'imagery_id' not in turn.trusted_tool_arguments['segment_instances']
    monkeypatch.setattr('app.agent.engine.input.get_user_imagery_metadata',AsyncMock(return_value={'band_roles':{'red':4,'nir':3}}))
    req.messages[0].content='这张影像计算 NDVI'
    turn=await build_turn_input(req,user_id='owner')
    assert turn.trusted_tool_arguments['calculate_ndvi']=={'imagery_id':'4256dea5c68b','red_band':4,'nir_band':3}

@pytest.mark.asyncio
async def test_preflight_blocks_nonintersecting_and_coarse_images(monkeypatch):
    from app.agent.tool_execution import prepare_tool_call, PrepareRejected
    monkeypatch.setenv('AGENT_RS_TOOLS_ENABLED','true'); get_settings.cache_clear()
    monkeypatch.setattr('app.agent.tool_execution.validate_tool_access',AsyncMock(return_value=None))
    meta={'bounds':[114.18,24.84,114.23,24.90], 'analysis_grid':{'crs':'EPSG:32649','pixel_size':[57.69,57.69]}}
    monkeypatch.setattr('app.agent.imagery_access.get_user_imagery_metadata',AsyncMock(return_value=meta))
    result=await prepare_tool_call('segment_instances',{'imagery_id':'4256dea5c68b','concepts':['building'],'bbox':[114.27,25.10,114.30,25.13],'bbox_crs':'EPSG:4326'},user_id='owner')
    assert isinstance(result,PrepareRejected) and result.error_detail=='invalid_roi'
    result=await prepare_tool_call('segment_instances',{'imagery_id':'4256dea5c68b','concepts':['building']},user_id='owner')
    assert result.error_detail=='unsupported_resolution'
    get_settings.cache_clear()

def test_small_scene_roi_retains_native_grid_and_missing_coverage_is_masked(tmp_path,monkeypatch):
    from app.agent.stac_search.model import SceneRecord
    from app.agent.stac_search.raster import compose_scene_tif
    assets={}
    for role, width in [('red',400),('nir',150)]:
        path=tmp_path/f'{role}.tif'
        with rasterio.open(path,'w',driver='GTiff',width=width,height=400,count=1,dtype='uint16',crs='EPSG:32649',transform=from_origin(500000,2500000,10,10)) as dst:
            dst.write(np.full((1,400,width),1000,dtype='uint16'))
        assets[role]=str(path)
    scene=SceneRecord(key='a'*12,source='earthsearch',item_id='test',collection='c',satellite='S2',datetime='2026-01-01',cloud_cover=0,bbox=[0,0,1,1],resolution_m=10,band_assets=assets,display_name='test')
    monkeypatch.setenv('AGENT_SCENE_WINDOW_MAX_PIXELS','256'); get_settings.cache_clear()
    roi=transform_bounds('EPSG:32649','EPSG:4326',500500,2498000,502000,2499500)
    out=tmp_path/'out.tif'; compose_scene_tif(scene,out,bbox=list(roi))
    with rasterio.open(out) as src:
        assert max(src.res)<10.2
        nir=src.read(1,masked=True)
        assert nir.mask[:,-1].all() and not nir.mask[:,0].any()
        assert np.isfinite(src.read(2)).all()
    get_settings.cache_clear()

def test_upload_preview_preserves_rgba_order_and_alpha(tmp_path):
    from app.services.raster_preview import generate_preview
    from PIL import Image
    path=tmp_path/'source.tif'
    data=np.full((4,10,10),0,dtype='uint8')
    data[0]=180; data[1]=90; data[2]=30; data[3]=255
    data[3,0,:]=0
    with rasterio.open(path,'w',driver='GTiff',width=10,height=10,count=4,dtype='uint8',crs='EPSG:4526',transform=from_origin(38500000,2700000,1,1)) as dst:
        dst.write(data)
        dst.colorinterp=(rasterio.enums.ColorInterp.red,rasterio.enums.ColorInterp.green,rasterio.enums.ColorInterp.blue,rasterio.enums.ColorInterp.alpha)
    preview=tmp_path/'preview.png'; generate_preview(path,preview,1024)
    pixels=np.asarray(Image.open(preview))
    assert list(pixels[2,2])==[180,90,30,255]
    assert not pixels[0,:,3].any()

@pytest.mark.asyncio
async def test_document_inventory_is_not_loaded_for_an_image_action(monkeypatch):
    from app.agent.request_builder import build_provider_request_context
    from app.schemas.chat import ChatRequest
    monkeypatch.setenv('DATABASE_ENABLED','false');get_settings.cache_clear()
    documents=AsyncMock(return_value='private document inventory')
    monkeypatch.setattr('app.agent.request_builder.build_document_inventory',documents)
    monkeypatch.setattr('app.agent.request_builder.build_imagery_inventory',AsyncMock(return_value=None))
    request=ChatRequest(messages=[{'role':'user','content':'这张影像提取建筑'}],use_memory=False)
    result=await build_provider_request_context(request,skip_retrieval=True,user_id='owner')
    documents.assert_not_called()
    assert not any('private document inventory' in m['content'] for m in result.messages)
    request.messages[0].content='根据文档里的方案提取建筑'
    await build_provider_request_context(request,skip_retrieval=True,user_id='owner')
    documents.assert_awaited_once()
    get_settings.cache_clear()

@pytest.mark.asyncio
async def test_agent_scene_import_produces_a_selectable_map_preview(monkeypatch):
    from app.agent.tools.scene_fetch.runner import run_scene_fetch
    from app.agent.tools.scene_fetch.schema import SceneFetchArguments
    monkeypatch.setattr('app.agent.tools.scene_fetch.runner.peek_current_user_id',lambda:'owner')
    monkeypatch.setattr('app.agent.tools.scene_fetch.runner.get_scene',lambda *args:object())
    monkeypatch.setattr('app.agent.tools.scene_fetch.runner.import_scene_as_imagery',AsyncMock(return_value={
        'imagery_id':'4256dea5c68b','satellite':'Landsat8','item_id':'LC08_TEST','band_roles':{'red':4},
        'preview_url':'/api/imagery/4256dea5c68b/results/preview.png','bounds':[112,23,115,26],
        'analysis_grid':{'width':3916,'height':3999,'pixel_size':[57.69,57.69]},
    }))
    result=await run_scene_fetch(SceneFetchArguments(scene_key='a'*12,reason='导入'))
    assert result.geospatial_result['imagery_id']=='4256dea5c68b'
    assert result.geospatial_result['type']=='preview'
    assert '57.69' in result.tool_context

def test_retrieval_context_has_a_hard_size_bound():
    text='source citation\n'+('lengthy document paragraph\n'*500)
    limited=service._limit_context(text,6000)
    assert len(limited)<=6000 and limited.startswith('source citation')
    assert '已省略' in limited
    assert service._limit_context(text,0)==''

@pytest.mark.asyncio
async def test_parallel_agents_share_one_retrieval():
    import asyncio
    from app.agent.engine.memory._common import run_query_once_per_turn
    from app.agent.engine.turn_context import turn_scope
    calls=0
    async def query():
        nonlocal calls
        calls+=1
        await asyncio.sleep(0)
        return 'result'
    with turn_scope():
        results=await asyncio.gather(*[run_query_once_per_turn('knowledge','same query',query) for _ in range(4)])
    assert results==['result']*4 and calls==1

def test_invalid_analysis_tool_is_hidden_until_new_scene_imported():
    from app.agent.engine.turn_context import TurnToolState,ToolInvocation
    from app.agent.types import ToolRunResult
    state=TurnToolState(precondition_blocks={'segment_instances':'invalid ROI'})
    assert not state.available('segment_instances')
    assert state.gpu_calls==0
    state.record(ToolInvocation(name='fetch_scene',arguments={},result=ToolRunResult(tool_context='imported')))
    assert state.available('segment_instances')

def test_import_selection_survives_a_later_analysis_or_report():
    from app.agent.engine.turn_context import TurnToolState,ToolInvocation
    from app.agent.types import ToolRunResult
    from app.agent.persistence import _assistant_metadata
    state=TurnToolState()
    state.record(ToolInvocation(name='fetch_scene',arguments={},result=ToolRunResult(tool_context='imported',geospatial_result={'type':'preview','imagery_id':'4256dea5c68b','result_url':'/new.png'})))
    state.record(ToolInvocation(name='segment_instances',arguments={},result=ToolRunResult(tool_context='later result',geospatial_result={'type':'instance_segmentation','imagery_id':'4256dea5c68b'})))
    assert state.latest_imported_imagery_id()=='4256dea5c68b'
    metadata=_assistant_metadata(finish_reason='stop',active_imagery_id=state.latest_imported_imagery_id(),geospatial_result=None,tool_result=None)
    assert metadata['active_imagery_id']=='4256dea5c68b'
