"""F10: raster masks, valid zero values and explicit statistical denominators."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.enums import ColorInterp
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "docker" / "rs_tools"))
from raster_utils import AllPixelsInvalidError, valid_mask
from compute_ndvi import compute as compute_ndvi
from compute_water_mask import compute as compute_water


def write_tif(path, data, *, nodata=None, mask=None, alpha=False):
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[2],
                       height=data.shape[1], count=data.shape[0], dtype=str(data.dtype),
                       nodata=nodata, transform=from_origin(0, data.shape[1], 1, 1)) as dst:
        dst.write(data)
        if data.dtype.kind == "f":
            dst.units = ("reflectance",) * len(data)
        if mask is not None:
            dst.write_mask(mask)
        if alpha:
            dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)


def test_untagged_integer_zero_is_valid_measurement(tmp_path):
    path = tmp_path / "zero.tif"
    write_tif(path, np.zeros((2, 2, 2), dtype="uint16"))
    with rasterio.open(path) as src:
        assert valid_mask(src, src.read((1, 2)), band_indexes=(1, 2)).all()


def test_partial_alpha_is_visible_and_zero_alpha_is_invalid(tmp_path):
    path = tmp_path / "rgba.tif"
    data = np.full((4, 2, 2), 20, dtype="uint8")
    data[3] = [[0, 64], [128, 255]]
    write_tif(path, data, alpha=True)
    with rasterio.open(path) as src:
        mask = valid_mask(src, src.read((1, 2, 3)), band_indexes=(1, 2, 3))
    assert mask.tolist() == [[False, True], [True, True]]


def test_required_band_masks_intersect_and_other_bands_do_not_constrain():
    masks = np.array([[[0, 255]], [[255, 0]], [[255, 255]]], dtype="uint8")
    src = SimpleNamespace(nodata=None, nodatavals=(None,) * 3,
                          dataset_mask=lambda: masks.max(axis=0),
                          read_masks=lambda indexes: masks[np.array(indexes) - 1])
    data = np.ones((2, 1, 2))
    assert not valid_mask(src, data, band_indexes=(1, 2)).any()
    assert valid_mask(src, [data[0]], band_indexes=(3,)).all()


def test_explicit_dataset_mask_is_not_overridden_by_valid_values(tmp_path):
    path = tmp_path / "mask.tif"
    write_tif(path, np.ones((2, 2, 2), dtype="float32"), mask=np.array([[0, 255], [255, 255]], dtype="uint8"))
    with rasterio.open(path) as src:
        assert valid_mask(src, src.read((1, 2)), band_indexes=(1, 2)).tolist() == [[False, True], [True, True]]


def test_mask_read_failure_is_not_silently_accepted():
    def broken():
        raise OSError("broken raster mask")
    src = SimpleNamespace(nodata=None, dataset_mask=broken)
    with pytest.raises(OSError, match="broken raster mask"):
        valid_mask(src, [np.ones((1, 1))])


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, -9999.0])
def test_single_required_band_bad_value_is_invalid(tmp_path, bad):
    path = tmp_path / "invalid.tif"
    data = np.ones((2, 1, 2), dtype="float32")
    data[0, 0, 0] = bad
    write_tif(path, data, nodata=-9999)
    with rasterio.open(path) as src:
        assert valid_mask(src, src.read((1, 2)), band_indexes=(1, 2)).tolist() == [[False, True]]


@pytest.mark.parametrize("compute,kwargs", [(compute_ndvi, {"red_band": 1, "nir_band": 2}), (compute_water, {"green_band": 1, "nir_band": 2})])
def test_statistics_counts_and_undefined_denominator(tmp_path, compute, kwargs):
    path = tmp_path / "counts.tif"
    data = np.array([[[.2, -.2], [-9999, .8]], [[.8, .2], [.8, .2]]], dtype="float32")
    write_tif(path, data, nodata=-9999)
    result = compute(input_path=str(path), output_dir=str(tmp_path / "out"), **kwargs)
    assert result["total_pixels"] == 4
    assert result["valid_pixels"] == 2
    assert result["nodata_pixels"] == 2
    assert result["valid_pixels"] + result["nodata_pixels"] == result["total_pixels"]
    assert result["nodata_pct"] == 50
    assert result["percentage_denominator"] == "total_pixels"
    if compute is compute_water:
        assert result["water_pct"] == 25
        assert result["water_valid_pct"] == 50


@pytest.mark.parametrize("compute,kwargs", [(compute_ndvi, {"red_band": 1, "nir_band": 2}), (compute_water, {"green_band": 1, "nir_band": 2})])
def test_all_undefined_indices_do_not_publish_zero_statistics(tmp_path, compute, kwargs):
    path = tmp_path / "undefined.tif"
    write_tif(path, np.zeros((2, 2, 2), dtype="float32"))
    out = tmp_path / "out"
    with pytest.raises(AllPixelsInvalidError, match="all_pixels_invalid"):
        compute(input_path=str(path), output_dir=str(out), **kwargs)
    assert not list(out.glob("*.tif"))


def test_alpha_remains_binding_with_explicit_all_valid_dataset_mask(tmp_path):
    path = tmp_path / "rgba_mask.tif"
    data = np.full((4, 1, 2), 20, dtype="uint8")
    data[3] = [[0, 255]]
    write_tif(path, data, alpha=True, mask=np.array([[255, 255]], dtype="uint8"))
    with rasterio.open(path) as src:
        assert valid_mask(src, src.read((1, 2, 3)), band_indexes=(1, 2, 3)).tolist() == [[False, True]]


@pytest.mark.parametrize("dtype,fill", [("uint32", 4000000001), ("int32", 2000000001)])
def test_mask_preserves_neighbor_of_large_integer_nodata(tmp_path, dtype, fill):
    path = tmp_path / "integer.tif"
    data = np.array([[[fill - 1, fill]], [[fill - 2, fill - 2]]], dtype=dtype)
    write_tif(path, data, nodata=fill)
    result = compute_ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)
    assert result["valid_pixels"] == 1
    assert result["nodata_pixels"] == 1
    assert result["mean"] == pytest.approx(-1 / (2 * fill - 3))


def test_statistics_of_finite_large_values_are_finite():
    from compute_ndvi import _stats
    import json
    stats = _stats(np.array([[1e30, -1e30]], dtype="float32"))
    assert np.isfinite(stats["std"])
    json.dumps(stats, allow_nan=False)
