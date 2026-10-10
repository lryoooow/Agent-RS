"""SAM3 instance-segmentation runner contract tests.

The legacy LandCover/U-Net runner was removed. This module keeps the historical
test filename so downstream test selectors continue to work while validating
the replacement capability.
"""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from pydantic import ValidationError
from rasterio.transform import from_origin

from app.agent.tools.instance_segment.runner import _write_rgb_png, run_instance_segment
from app.agent.tools.instance_segment.schema import InstanceSegmentArguments
from app.core.settings import get_settings


IMAGERY_ID = "94e758f38ede"


def _prepare_imagery(root: Path, *, count: int = 3) -> Path:
    imagery_dir = root / IMAGERY_ID
    imagery_dir.mkdir()
    data = np.zeros((count, 4, 4), dtype=np.uint8)
    data[0] = 180
    data[1] = 90
    data[2] = 30
    with rasterio.open(
        imagery_dir / "working.tif",
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=count,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(100.0, 20.0, 0.01, 0.01),
    ) as dst:
        dst.write(data)
        dst.colorinterp = (
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
        )
    (imagery_dir / "metadata.json").write_text(
        '{"bounds":[100.0,19.96,100.04,20.0]}', encoding="utf-8"
    )
    return imagery_dir


def test_schema_normalizes_and_deduplicates_concepts() -> None:
    args = InstanceSegmentArguments(
        imagery_id=IMAGERY_ID,
        concepts=[" Building ", "building", "solar   panel"],
    )
    assert args.concepts == ["building", "solar panel"]


@pytest.mark.parametrize("concept", ["", "bad/name", "line\nbreak"])
def test_schema_rejects_invalid_concepts(concept: str) -> None:
    with pytest.raises(ValidationError):
        InstanceSegmentArguments(imagery_id=IMAGERY_ID, concepts=[concept])


@pytest.mark.asyncio
async def test_runner_rejects_invalid_imagery_id() -> None:
    result = await run_instance_segment(
        InstanceSegmentArguments.model_construct(imagery_id="BADID", concepts=["building"])
    )
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_runner_reports_disabled_local_service(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SAM3_ENABLED", "false")
    get_settings.cache_clear()
    try:
        result = await run_instance_segment(
            InstanceSegmentArguments(imagery_id=IMAGERY_ID, concepts=["building"])
        )
        assert result.error == "service_disabled"
        assert result.geospatial_result is None
        assert result.artifacts == []
    finally:
        get_settings.cache_clear()


def test_rgb_export_success_keeps_documented_channel_order(tmp_path: Path) -> None:
    imagery_dir = _prepare_imagery(tmp_path)
    output = tmp_path / "input.png"
    grid = _write_rgb_png(imagery_dir / "working.tif", output, 1, 2, 3)
    pixel = np.asarray(Image.open(output))[1, 1]
    assert pixel.tolist() == [180, 90, 30]
    assert grid == (4, 4)  # 小于像元上限：不降采样，返回源网格


# ---- G3 SAM3 输入像元预算（bugfix-plan-G，2026-10-09）----
# 历史 bug：_write_rgb_png 无条件 masked=True 整幅读取，730KB 的 9000x9000 源
# （81M 像元 > 服务端 SAM3_MAX_PIXELS=64M）即迫使后端主进程分配 1390MB（tracemalloc
# 复现），且产出的 PNG 注定被服务端拒绝——先读入再被拒。修复：读取前检查
# width×height，超过 settings.sam3_max_pixels（默认 64M，与 ops/sam3_service.py
# 同名同默认）按 sqrt 比例降采样（out_shape + bilinear），并把实际推理网格
# 传入 _promote_outputs 对齐输出栅格尺寸/transform/像元面积。

import json as _json

import pytest
from rasterio.enums import Resampling as _Resampling

from app.agent.tools.instance_segment.runner import _promote_outputs


def _make_grid_tif(path: Path, *, width: int, height: int, count: int = 3, dtype: str = "uint16") -> None:
    data = np.zeros((count, height, width), dtype=dtype)
    for band in range(count):
        data[band] = band * 30 + 40
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=count, dtype=dtype,
        crs="EPSG:4326", transform=from_origin(100.0, 20.0, 0.01, 0.01),
    ) as dst:
        dst.write(data)


class _FakeRasterSource:
    """记录 read 调用参数的假 dataset：锁定"读取必须带 out_shape 预算，禁止整幅读"。"""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.calls: list[dict] = []

    def read(self, indexes, *, masked=None, out_shape=None, resampling=None):
        self.calls.append({"indexes": indexes, "out_shape": out_shape, "resampling": resampling})
        if out_shape is None:
            out_h, out_w = self.height, self.width
        else:
            _, out_h, out_w = out_shape
        data = np.full((len(indexes), out_h, out_w), 128, dtype=np.uint16)
        mask = np.zeros(data.shape, dtype=bool)
        return np.ma.masked_array(data, mask=mask)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_write_rgb_png_never_reads_full_res_beyond_cap(monkeypatch, tmp_path: Path) -> None:
    """回归核心：超过 sam3_max_pixels 时必须以预算内 out_shape 读取（禁止先整幅读入再被服务端拒）。"""
    import rasterio as _rasterio

    fake = _FakeRasterSource(width=3000, height=3000)  # 9M 像元
    monkeypatch.setenv("SAM3_MAX_PIXELS", "1000000")  # 1M 上限 → 1000x1000
    get_settings.cache_clear()
    monkeypatch.setattr(_rasterio, "open", lambda *_a, **_k: fake)
    try:
        grid = _write_rgb_png(tmp_path / "src.tif", tmp_path / "input.png", 1, 2, 3)
    finally:
        get_settings.cache_clear()

    assert grid == (1000, 1000)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["out_shape"] == (3, 1000, 1000), "必须以预算内 out_shape 读取，不得整幅读入"
    assert call["out_shape"][1] * call["out_shape"][2] <= 1_000_000
    assert call["resampling"] == _Resampling.bilinear
    with Image.open(tmp_path / "input.png") as im:
        assert im.size == (1000, 1000)


def test_write_rgb_png_normal_size_reads_full_no_downsample(monkeypatch, tmp_path: Path) -> None:
    """正常：小于上限时与修复前一致——整读（masked、无 out_shape），返回源网格。"""
    import rasterio as _rasterio

    fake = _FakeRasterSource(width=200, height=150)  # 30k < 64M 默认上限
    monkeypatch.setattr(_rasterio, "open", lambda *_a, **_k: fake)
    grid = _write_rgb_png(tmp_path / "src.tif", tmp_path / "input.png", 1, 2, 3)

    assert grid == (200, 150)
    assert fake.calls[0]["out_shape"] is None  # 与修复前完全同款调用
    with Image.open(tmp_path / "input.png") as im:
        assert im.size == (200, 150)


def test_write_rgb_png_cap_boundary_exact_pass(tmp_path: Path) -> None:
    """边界：像元数恰好等于上限不降采样（> 才触发），返回原网格。"""
    _make_grid_tif(tmp_path / "exact.tif", width=100, height=100)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SAM3_MAX_PIXELS", "10000")
        get_settings.cache_clear()
        try:
            grid = _write_rgb_png(tmp_path / "exact.tif", tmp_path / "out.png", 1, 2, 3)
        finally:
            get_settings.cache_clear()
    assert grid == (100, 100)
    with Image.open(tmp_path / "out.png") as im:
        assert im.size == (100, 100)


def _fabricate_service_outputs(job_dir: Path, *, grid_w: int, grid_h: int) -> dict:
    """伪造 ops/sam3_service.py 的产物（overlay/union/labels/instances/metrics）。"""
    Image.new("RGB", (grid_w, grid_h), (60, 60, 60)).save(job_dir / "sam3_overlay.png")
    Image.new("L", (grid_w, grid_h), 255).save(job_dir / "sam3_union.png")
    labels = np.zeros((grid_h, grid_w), dtype=np.uint32)
    labels[:, : grid_w // 2] = 1  # 左半为一个实例
    np.save(job_dir / "sam3_labels.npy", labels, allow_pickle=False)
    (job_dir / "sam3_instances.json").write_text(
        _json.dumps([{"label_id": 1, "id": "building-0-0", "concept": "building",
                      "score": 0.9, "bbox_xyxy": [0, 0, grid_w // 2, grid_h],
                      "mask_pixels": int(labels.sum()), "touches_internal_tile_edge": False,
                      "source_tiles": [0]}]),
        encoding="utf-8",
    )
    (job_dir / "sam3_metrics.json").write_text("{}", encoding="utf-8")
    return {
        "overlay_png": "sam3_overlay.png", "union_png": "sam3_union.png",
        "labels_npy": "sam3_labels.npy", "instances_json": "sam3_instances.json",
        "metrics_json": "sam3_metrics.json", "counts": {"building": 1},
    }


def test_promote_outputs_downsampled_grid_geometry_consistent(tmp_path: Path) -> None:
    """降采样路径：mask/labels 按推理网格尺寸 + 缩放 transform 写出，geojson 坐标落回源范围。

    独立期望（手算）：200x200 源、像元 0.01°、推理网格 100x100 → 输出像元 0.02°；
    实例占左半 50 像元宽 → geojson 经度跨度 = 50×0.02 = 1.0。
    """
    source = tmp_path / "source.tif"
    _make_grid_tif(source, width=200, height=200)
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    results_dir = tmp_path / "results"
    results_dir.mkdir()  # 真实 runner 在调用前已建好结果目录
    result = _fabricate_service_outputs(job_dir, grid_w=100, grid_h=100)

    promoted = _promote_outputs(
        job_dir, results_dir, source, result, inference_grid=(100, 100)
    )

    with rasterio.open(tmp_path / "results" / promoted["mask_tif"]) as mask:
        assert (mask.width, mask.height) == (100, 100)
        assert mask.transform.a == pytest.approx(0.02)  # 0.01 × 200/100
        assert mask.transform.e == pytest.approx(-0.02)
        assert mask.bounds.right == pytest.approx(100.0 + 200 * 0.01)  # 地理范围与源一致
    with rasterio.open(tmp_path / "results" / promoted["labels_tif"]) as labels:
        assert labels.read(1).max() == 1

    geojson = _json.loads((tmp_path / "results" / promoted["geojson"]).read_text(encoding="utf-8"))
    assert geojson["features"], "降采样路径 geojson 不应为空"
    ring = geojson["features"][0]["geometry"]["coordinates"][0]
    xs = [coord[0] for coord in ring]
    assert max(xs) - min(xs) == pytest.approx(1.0, abs=1e-6)  # 50 像元 × 0.02°（手算）


def test_promote_outputs_same_grid_keeps_legacy_behavior(tmp_path: Path) -> None:
    """回归：不传 inference_grid（或与源一致）时与修复前逐项一致——尺寸=源、transform=源。"""
    source = tmp_path / "source.tif"
    _make_grid_tif(source, width=100, height=80)
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    result = _fabricate_service_outputs(job_dir, grid_w=100, grid_h=80)

    promoted = _promote_outputs(job_dir, results_dir, source, result)  # 不传 grid

    with rasterio.open(tmp_path / "results" / promoted["mask_tif"]) as mask:
        assert (mask.width, mask.height) == (100, 80)
    with rasterio.open(source) as src, rasterio.open(tmp_path / "results" / promoted["mask_tif"]) as mask:
        assert mask.transform == src.transform
    assert promoted["area_m2"] is not None  # EPSG:4326 球面近似路径正常出面积


def test_promote_outputs_rejects_grid_mismatch(tmp_path: Path) -> None:
    """异常：服务端产物网格与推理源不一致 → 明确 ValueError（防御服务端/后端网格失配）。"""
    source = tmp_path / "source.tif"
    _make_grid_tif(source, width=100, height=80)
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    result = _fabricate_service_outputs(job_dir, grid_w=64, grid_h=48)  # 与源 100x80 不符

    with pytest.raises(ValueError, match="grid does not match"):
        _promote_outputs(job_dir, tmp_path / "results", source, result)


@pytest.mark.parametrize("size", [(9000, 1), (1, 9000)])
def test_rgb_budget_also_bounds_thin_rasters(monkeypatch, tmp_path, size):
    fake = _FakeRasterSource(width=size[0], height=size[1])
    monkeypatch.setenv("SAM3_MAX_PIXELS", "100")
    get_settings.cache_clear()
    monkeypatch.setattr(rasterio, "open", lambda *args, **kwargs: fake)
    try:
        width, height = _write_rgb_png(tmp_path / "thin.tif", tmp_path / "thin.png", 1, 2, 3)
    finally:
        get_settings.cache_clear()
    assert 1 <= width * height <= 100
    assert fake.calls[0]["out_shape"] == (3, height, width)


@pytest.mark.asyncio
async def test_cancellation_does_not_delete_inputs_while_inference_is_running(monkeypatch,tmp_path):
    import asyncio,httpx
    import app.agent.tools.instance_segment.runner as module
    directory=_prepare_imagery(tmp_path)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR",str(tmp_path));monkeypatch.setenv("SAM3_ENABLED","true");get_settings.cache_clear()
    started,release=asyncio.Event(),asyncio.Event()
    paths=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def post(self,url,json):
            path=Path(json["input_path"]);paths.append(path);started.set();await release.wait()
            assert path.is_file()
            return httpx.Response(500,headers={"X-SAM3-Settled":"1"},request=httpx.Request("POST",url))
    monkeypatch.setattr(module.httpx,"AsyncClient",Client)
    task=asyncio.create_task(run_instance_segment(InstanceSegmentArguments(imagery_id=IMAGERY_ID,concepts=["building"])))
    await asyncio.wait_for(started.wait(),3);task.cancel();await asyncio.sleep(.02)
    assert not task.done() and paths[0].is_file()
    release.set()
    with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,3)
    assert not paths[0].exists() and not list((directory/"results").glob(".sam3_*"))


@pytest.mark.asyncio
async def test_network_timeout_retains_private_input_until_gpu_outcome_is_known(monkeypatch,tmp_path):
    import httpx
    import app.agent.tools.instance_segment.runner as module
    directory=_prepare_imagery(tmp_path)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR",str(tmp_path));monkeypatch.setenv("SAM3_ENABLED","true");get_settings.cache_clear()
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def post(self,url,json):raise httpx.ReadTimeout("timed out")
    monkeypatch.setattr(module.httpx,"AsyncClient",Client)
    result=await run_instance_segment(InstanceSegmentArguments(imagery_id=IMAGERY_ID,concepts=["building"]))
    assert result.error=="inference_timeout" and not result.geospatial_result
    jobs=list((directory/"results").glob(".sam3_*"));assert len(jobs)==1
    assert (jobs[0]/"input.png").is_file() and (jobs[0]/"outcome_unknown.json").is_file()
    assert not list((directory/"results").glob("*.tif"))


def test_sam3_service_output_paths_cannot_escape_job_directory(tmp_path):
    directory=_prepare_imagery(tmp_path);job=tmp_path/"job";job.mkdir();results=tmp_path/"out";results.mkdir()
    outside=tmp_path/"private.png";outside.write_bytes(b"original")
    with pytest.raises(ValueError,match="invalid SAM3 output path"):
        _promote_outputs(job,results,directory/"working.tif",{"overlay_png":"../private.png","counts":{}})
    assert outside.read_bytes()==b"original" and not list(results.iterdir())
