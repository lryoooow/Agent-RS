from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "docker" / "rs_tools"))
from compute_cloud_mask import CLEAR, CLOUD, SHADOW, NODATA, UNKNOWN, SNOW, TERRAIN_SHADOW, compute


def _source(path: Path, *, shape=(2, 2), sensor="Sentinel-2B", values=None):
    data = np.full((4, *shape), .45, dtype=np.float32) if values is None else values
    with rasterio.open(path, "w", driver="GTiff", width=shape[1], height=shape[0], count=data.shape[0],
                       dtype=str(data.dtype), crs="EPSG:4326", transform=from_origin(100, 20, .01, .01)) as dst:
        dst.write(data)
        dst.units = ("reflectance",) * data.shape[0]
        dst.update_tags(SENSOR=sensor)


def _quality(path: Path, values, *, kind="sentinel2_scl", sensor="Sentinel-2B", tags=None,
             transform=None, crs="EPSG:4326", dtype="uint8", count=1):
    values = np.asarray(values, dtype=dtype)
    defaults = {"QA_TYPE": kind, "QA_SENSOR": sensor, "QA_SOURCE": "sentinel2" if kind == "sentinel2_scl" else "landsat",
                "QA_ITEM_ID": "test-scene"}
    if tags is not None:
        defaults = tags
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0], count=count,
                       dtype=dtype, crs=crs, transform=transform or from_origin(100, 20, .01, .01)) as dst:
        for band in range(1, count + 1):
            dst.write(values, band)
        dst.update_tags(**defaults)


def _run(tmp_path, **kwargs):
    return compute(input_path=str(tmp_path / "working.tif"), output_dir=str(tmp_path / "results"), **kwargs)


def _classes(tmp_path, stats):
    with rasterio.open(tmp_path / "results" / stats["output_tif"]) as src:
        assert src.dtypes == ("uint8",)
        assert src.tags()["MASK_METHOD"] == stats["method"]
        return src.read(1)


def test_default_cloud_method_rejects_missing_quality_product(tmp_path):
    _source(tmp_path / "working.tif")
    with pytest.raises(ValueError, match="quality_mask_unavailable"):
        _run(tmp_path)
    assert not (tmp_path / "results").exists()


def test_default_cloud_method_uses_quality_not_bright_roof(tmp_path):
    _source(tmp_path / "working.tif")
    _quality(tmp_path / "quality.tif", np.full((2, 2), 5))
    stats = _run(tmp_path)
    assert stats["cloud_pct"] == 0.0 and stats["clear_pct"] == 100.0
    assert stats["method"] == "quality_mask" and stats["method_validation"] == "product_flags"


def test_scl_all_classes_keep_unknown_snow_and_terrain_separate(tmp_path):
    _source(tmp_path / "working.tif", shape=(1, 12))
    _quality(tmp_path / "quality.tif", np.arange(12).reshape(1, 12))
    stats = _run(tmp_path)
    assert _classes(tmp_path, stats).tolist() == [[NODATA, NODATA, TERRAIN_SHADOW, SHADOW, CLEAR, CLEAR, CLEAR,
                                                 UNKNOWN, CLOUD, CLOUD, CLOUD, SNOW]]
    assert stats["cloud_pixel_count"] == 3 and stats["cloud_pct"] == 25.0 and stats["cloud_valid_pct"] == 30.0
    assert stats["clear_pixel_count"] == 3 and stats["shadow_pixel_count"] == 1
    assert stats["unknown_pixel_count"] == stats["snow_pixel_count"] == stats["terrain_shadow_pixel_count"] == 1
    assert stats["total_pixels"] == 12 and stats["valid_pixels"] == 10 and stats["nodata_pixels"] == 2


@pytest.mark.parametrize(("code", "pct_key"), [(8, "cloud_pct"), (9, "cloud_pct"), (10, "cloud_pct"),
                                                 (3, "shadow_pct"), (7, "unknown_pct"), (11, "snow_pct"),
                                                 (2, "terrain_shadow_pct"), (5, "clear_pct")])
def test_quality_product_can_report_zero_or_full_fraction_without_percentile_cap(tmp_path, code, pct_key):
    _source(tmp_path / "working.tif")
    _quality(tmp_path / "quality.tif", np.full((2, 2), code))
    stats = _run(tmp_path)
    assert stats[pct_key] == 100.0
    assert stats["nodata_pct"] == 0.0


def test_landsat8_bits_and_priority_are_decoded_by_usgs_layout(tmp_path):
    qa = np.array([[0, 64, 8, 16, 32, 2, 4, 8 | 16 | 32 | 1, 1, 64 | 128, 64 | 16, 64 | 32]], dtype="uint16")
    _source(tmp_path / "working.tif", shape=qa.shape, sensor="Landsat 8")
    _quality(tmp_path / "quality.tif", qa, kind="landsat_c2_qa_pixel", sensor="Landsat 8", dtype="uint16")
    stats = _run(tmp_path)
    assert _classes(tmp_path, stats).tolist() == [[UNKNOWN, CLEAR, CLOUD, SHADOW, SNOW, CLOUD, CLOUD,
                                                 NODATA, NODATA, CLEAR, SHADOW, SNOW]]
    assert stats["cloud_pixel_count"] == 3 and stats["shadow_pixel_count"] == 2
    assert stats["unknown_pixel_count"] == 1 and stats["snow_pixel_count"] == 2


@pytest.mark.parametrize("sensor", ["Landsat 4", "Landsat 5", "Landsat 7"])
def test_landsat_tm_etm_bit2_is_not_cirrus(tmp_path, sensor):
    _source(tmp_path / "working.tif", sensor=sensor)
    _quality(tmp_path / "quality.tif", [[4, 4], [64, 64]], kind="landsat_c2_qa_pixel", sensor=sensor, dtype="uint16")
    stats = _run(tmp_path)
    assert stats["cloud_pct"] == 0.0 and stats["unknown_pct"] == stats["clear_pct"] == 50.0


def test_nan_source_pixel_is_invalid_even_when_qa_says_cloud(tmp_path):
    data = np.full((4, 2, 2), .45, dtype=np.float32)
    data[2, 0, 0] = np.nan
    _source(tmp_path / "working.tif", values=data)
    _quality(tmp_path / "quality.tif", [[9, 9], [9, 9]])
    stats = _run(tmp_path)
    assert stats["cloud_pct"] == 75.0 and stats["cloud_valid_pct"] == 100.0
    assert stats["nodata_pct"] == 25.0 and _classes(tmp_path, stats)[0, 0] == NODATA


@pytest.mark.parametrize("qa", [[[0, 0], [0, 0]], [[1, 1], [1, 1]]])
def test_all_invalid_qa_never_returns_zero_cloud_as_success(tmp_path, qa):
    _source(tmp_path / "working.tif")
    _quality(tmp_path / "quality.tif", qa)
    with pytest.raises(ValueError, match="all_pixels_invalid"):
        _run(tmp_path)


@pytest.mark.parametrize("change", ["size", "transform", "crs", "float", "multi", "range", "type", "sensor", "source", "item"])
def test_invalid_quality_never_falls_back_to_heuristic(tmp_path, change):
    _source(tmp_path / "working.tif")
    options = {}
    values = [[5, 5], [5, 5]]
    tags = {"QA_TYPE": "sentinel2_scl", "QA_SENSOR": "Sentinel-2B", "QA_SOURCE": "sentinel2", "QA_ITEM_ID": "test-scene"}
    if change == "size": values = [[5]]
    if change == "transform": options["transform"] = from_origin(101, 20, .01, .01)
    if change == "crs": options["crs"] = "EPSG:3857"
    if change == "float": options["dtype"] = "float32"
    if change == "multi": options["count"] = 2
    if change == "range": values = [[12, 5], [5, 5]]
    if change == "type": tags["QA_TYPE"] = "unknown"
    if change == "sensor": tags["QA_SENSOR"] = "Sentinel-2A"
    if change == "source": tags["QA_SOURCE"] = "arbitrary"
    if change == "item": tags.pop("QA_ITEM_ID")
    _quality(tmp_path / "quality.tif", values, tags=tags, **options)
    with pytest.raises(ValueError, match="quality_mask_invalid"):
        _run(tmp_path)
    assert not (tmp_path / "results").exists()


def test_quality_arguments_cannot_select_another_imagery_directory(tmp_path):
    _source(tmp_path / "working.tif")
    elsewhere = tmp_path / "another" / "quality.tif"
    with pytest.raises(ValueError, match="quality_mask_invalid"):
        _run(tmp_path, quality_path=str(elsewhere))


def test_quality_type_argument_must_match_product_tag(tmp_path):
    _source(tmp_path / "working.tif")
    _quality(tmp_path / "quality.tif", [[5, 5], [5, 5]])
    with pytest.raises(ValueError, match="quality_mask_invalid"):
        _run(tmp_path, quality_type="landsat_c2_qa_pixel")


def test_explicit_heuristic_never_claims_cloud_fraction(tmp_path):
    _source(tmp_path / "working.tif")
    stats = _run(tmp_path, method="heuristic")
    assert stats["candidate_bright_pct"] == 100.0
    for key in ("cloud_pct", "shadow_pct", "clear_pct", "cloud_valid_pct", "cloud_pixel_count"):
        assert stats[key] is None
    assert stats["method"] == "heuristic" and stats["method_validation"] == "unvalidated"


@pytest.mark.parametrize("method", ["bad", "", "fmask"])
def test_unknown_method_is_rejected(tmp_path, method):
    _source(tmp_path / "working.tif")
    with pytest.raises(ValueError, match="invalid_cloud_method"):
        _run(tmp_path, method=method)


def test_heuristic_cannot_mix_quality_arguments(tmp_path):
    _source(tmp_path / "working.tif")
    with pytest.raises(ValueError, match="invalid_cloud_method"):
        _run(tmp_path, method="heuristic", quality_type="sentinel2_scl")


def test_quality_reruns_preserve_previous_mask(tmp_path):
    _source(tmp_path / "working.tif")
    _quality(tmp_path / "quality.tif", [[5, 5], [5, 5]])
    first = _run(tmp_path)
    previous = (tmp_path / "results" / first["output_tif"]).read_bytes()
    _quality(tmp_path / "quality.tif", [[9, 9], [9, 9]])
    second = _run(tmp_path)
    assert first["output_tif"] != second["output_tif"]
    assert (tmp_path / "results" / first["output_tif"]).read_bytes() == previous
    assert second["cloud_pct"] == 100.0 and first["cloud_pct"] == 0.0


@pytest.mark.parametrize("sensor", ["Landsat 4", "Landsat 5", "Landsat 7"])
def test_landsat47_known_clear_bit_issue_over_water(tmp_path, sensor):
    _source(tmp_path / "working.tif", sensor=sensor)
    _quality(tmp_path / "quality.tif", [[128, 128 | 2], [128 | 8, 128 | 16 | 32]],
             kind="landsat_c2_qa_pixel", sensor=sensor, dtype="uint16")
    stats = _run(tmp_path)
    assert _classes(tmp_path, stats).tolist() == [[CLEAR, CLOUD], [CLOUD, SHADOW]]
    assert stats["clear_pct"] == 25.0 and stats["cloud_pct"] == 50.0


@pytest.mark.parametrize("qa_value", [64 | (2 << 8), 64 | (2 << 10), 64 | (2 << 12), 64 | (2 << 14)])
def test_landsat_medium_or_reserved_confidence_is_not_clear(tmp_path, qa_value):
    _source(tmp_path / "working.tif", sensor="Landsat 9")
    _quality(tmp_path / "quality.tif", [[qa_value, qa_value], [qa_value, qa_value]],
             kind="landsat_c2_qa_pixel", sensor="Landsat 9", dtype="uint16")
    stats = _run(tmp_path)
    assert stats["unknown_pct"] == 100.0 and stats["clear_pct"] == 0.0 and stats["cloud_pct"] == 0.0


def test_landsat_standard_low_confidence_clear_value_is_retained(tmp_path):
    _source(tmp_path / "working.tif", sensor="Landsat 8")
    _quality(tmp_path / "quality.tif", [[21824, 21824], [21824, 21824]],
             kind="landsat_c2_qa_pixel", sensor="Landsat 8", dtype="uint16")
    stats = _run(tmp_path)
    assert stats["clear_pct"] == 100.0 and stats["unknown_pct"] == 0.0


def test_quality_source_partial_alpha_and_explicit_mask_are_respected(tmp_path):
    from rasterio.enums import ColorInterp
    source = tmp_path / "working.tif"
    data = np.full((4, 2, 2), 1, dtype="uint8")
    data[3] = [[255, 255], [0, 255]]
    with rasterio.open(source, "w", driver="GTiff", width=2, height=2, count=4, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(100, 20, .01, .01)) as src:
        src.write(data)
        src.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
        src.write_mask(np.array([[255, 0], [255, 255]], dtype="uint8"))
        src.update_tags(SENSOR="Sentinel-2B")
    _quality(tmp_path / "quality.tif", [[9, 9], [9, 9]])
    stats = _run(tmp_path)
    assert stats["cloud_pct"] == 50.0 and stats["cloud_valid_pct"] == 100.0
    assert _classes(tmp_path, stats).tolist() == [[CLOUD, NODATA], [NODATA, CLOUD]]


def test_corrupt_qa_fails_with_stable_input_error(tmp_path):
    _source(tmp_path / "working.tif")
    (tmp_path / "quality.tif").write_bytes(b"not a TIFF")
    with pytest.raises(ValueError, match="quality_mask_invalid"):
        _run(tmp_path)
