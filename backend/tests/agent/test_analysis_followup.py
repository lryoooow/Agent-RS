import importlib.util
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.enums import ColorInterp
from rasterio.transform import from_origin

from app.services.raster_semantics import band_semantics, grid_context, resolve_rgb
from app.agent.request_builder import _format_imagery_line
from app.agent.tools.band_composite.schema import required_bands_for_composite


def load_module(name, folder):
    path = Path(__file__).resolve().parents[3] / "docker" / folder / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_rgba(path, size=4, resolution=1):
    data = np.stack([np.full((size, size), v, dtype="uint8") for v in (60, 90, 120, 255)])
    data[3, 0, 0] = 0
    with rasterio.open(path, "w", driver="GTiff", width=size, height=size, count=4,
                       dtype="uint8", crs="EPSG:3857", transform=from_origin(100, 200, resolution, resolution)) as dst:
        dst.write(data)
        dst.colorinterp = (ColorInterp.gray, ColorInterp.undefined, ColorInterp.undefined, ColorInterp.alpha)
    return data


def test_named_preview_resolves_rgba_and_preserves_byte_channels_alpha_and_history(tmp_path):
    data = write_rgba(tmp_path / "source.tif")
    roles = band_semantics(tmp_path / "source.tif")["band_roles"]
    bands = list(required_bands_for_composite("true_color", None, roles).values())
    assert bands == [1, 2, 3]
    render = load_module("compute_band_composite", "rs_tools").render
    first = render(input_path=str(tmp_path / "source.tif"), output_dir=str(tmp_path), mode="true_color", bands=bands)
    second = render(input_path=str(tmp_path / "source.tif"), output_dir=str(tmp_path), mode="true_color", bands=bands)
    assert first["output_png"] != second["output_png"]
    assert np.array_equal(np.asarray(Image.open(tmp_path / first["output_png"])), np.moveaxis(data, 0, -1))
    with pytest.raises(ValueError, match="近红外"):
        required_bands_for_composite("false_color", None, roles)
    assert list(required_bands_for_composite("false_color", None, {"nir": 6, "red": 2, "green": 3}).values()) == [6, 2, 3]
    assert list(required_bands_for_composite("custom", [3, 2, 1], roles).values()) == [3, 2, 1]


def test_original_provenance_analysis_grid_and_alpha_are_consistent(tmp_path):
    write_rgba(tmp_path / "source.tif", size=6, resolution=2)
    write_rgba(tmp_path / "working.tif", size=4, resolution=3)
    # Historical working writer inserted RGB, but original incomplete labels win.
    with rasterio.open(tmp_path / "working.tif", "r+") as dst:
        dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
    meta = band_semantics(tmp_path / "working.tif")
    assert meta["band_roles_source"] == "positional_rgba"
    assert resolve_rgb(tmp_path / "working.tif", {"red": 3, "green": 2, "blue": 1}) == {"red": 1, "green": 2, "blue": 3}
    context = grid_context(tmp_path / "working.tif")
    assert context["source_grid"]["width"] == 6 and context["analysis_grid"]["width"] == 4
    assert context["resampled"] and context["analysis_grid"]["pixel_size"] == [3, 3]
    line = _format_imagery_line("fec6252c9325", {**meta, **context})
    assert "原图网格 6x6" in line and "分析网格 4x4" in line and "不是元数据冲突" in line
    inspection = load_module("compute_raster_inspect", "rs_tools").inspect(str(tmp_path / "working.tif"))
    alpha = inspection["alpha_statistics"][0]
    assert alpha["opaque_value"] == 255 and alpha["opaque_percentage"] == 93.75
    assert alpha["transparent_percentage"] == 6.25


def test_unknown_multispectral_cannot_silently_inherit_gf2(tmp_path):
    path = tmp_path / "source.tif"
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=4, dtype="uint16") as dst:
        dst.write(np.ones((4, 2, 2), dtype="uint16"))
    requested = {"red": 3, "green": 2, "blue": 1}
    with pytest.raises(ValueError, match="缺少"):
        resolve_rgb(path, requested)
    assert resolve_rgb(path, requested, explicit=True) == requested


def test_detector_tile_offsets_class_mapping_and_seam_deduplication(monkeypatch):
    module = load_module("tiled_obb", "rs_detect")
    calls = []
    class Tensor:
        def __init__(self, values): self.values = np.asarray(values)
        def cpu(self): return self
        def numpy(self): return self.values
    class FakeYOLO:
        names = {0: "ship", 1: "small vehicle"}
        def __init__(self, *args, **kwargs): pass
        def predict(self, **kwargs):
            calls.append(kwargs)
            assert kwargs["source"][0, 0].tolist() == [30, 20, 10]
            x = 800 if len(calls) == 1 else 288
            obb = SimpleNamespace(xyxyxyxy=Tensor([[[x, 10], [x+20, 10], [x+20, 30], [x, 30]]]), cls=Tensor([0]), conf=Tensor([0.9]))
            return [SimpleNamespace(obb=obb)]
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeYOLO))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), inference_mode=nullcontext))
    monkeypatch.setattr(module.Path, "is_file", lambda self: True)
    monkeypatch.setenv("RS_DETECT_REQUIRE_GPU", "0")
    rgb = np.empty((1024, 1536, 3), dtype="uint8")
    rgb[:] = [10, 20, 30]
    boxes, runtime = module.infer(rgb, 0.5, ["small-vehicle", "ship"])
    assert runtime["tile_count"] == 2 and len(boxes) == 1
    assert boxes[0]["class_id"] == 1 and boxes[0]["polygon"][0] == 800
    distinct_class = {**boxes[0], "class_id": 0}
    assert len(module.merge_rotated([boxes[0], distinct_class])) == 2


def test_detection_result_exports_have_correct_media_types():
    from app.api.routes.imagery import _result_media_type
    assert _result_media_type("boxes.geojson") == "application/geo+json"
    assert _result_media_type("boxes.json") == "application/json"
