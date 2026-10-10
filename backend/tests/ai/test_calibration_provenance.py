"""F13: use declared calibration provenance, never guess from pixel magnitude."""
from pathlib import Path
import sys
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "docker" / "rs_tools"))
from compute_ndvi import compute as ndvi
from compute_spectral_index import compute as spectral
from raster_utils import AllPixelsInvalidError, StaleS2CompositeError, UncalibratedInputError


def write(path, data, *, tags=None, band_tags=None, scales=None, offsets=None, units=None):
    data = np.asarray(data, dtype="float32").reshape(len(data), 1, -1)
    with rasterio.open(path, "w", driver="GTiff", height=1, width=data.shape[2], count=len(data),
                       dtype="float32", transform=from_origin(0, 1, 1, 1)) as dst:
        dst.write(data)
        if tags:
            dst.update_tags(**tags)
        if band_tags:
            for i, meta in enumerate(band_tags, 1):
                dst.update_tags(i, **meta)
        if scales:
            dst.scales = scales
        if offsets:
            dst.offsets = offsets
        if units:
            dst.units = units


def test_small_float_values_without_quantity_do_not_prove_reflectance(tmp_path):
    path = tmp_path / "unknown.tif"
    write(path, [.08, .06, .1, .3])
    with pytest.raises(UncalibratedInputError, match="uncalibrated_input"):
        spectral(input_path=str(path), output_dir=str(tmp_path / "out"), index_type="evi")


def test_declared_float_dn_is_calibrated_before_value_range_checks(tmp_path):
    path = tmp_path / "dn.tif"
    write(path, [1., 3.], tags={"REFL_SCALE": ".0001", "REFL_OFFSET": "-.00005"})
    stats = ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)
    assert stats["mean"] == pytest.approx(2 / 3)
    assert stats["calibration"]["bands"]["red"]["scale"] == .0001
    assert stats["calibration"]["bands"]["red"]["offset"] == -.00005
    assert stats["calibration"]["method_version"] == "reflectance-v2"


def test_distinct_band_scale_offset_matches_physical_reflectance(tmp_path):
    path = tmp_path / "per_band.tif"
    write(path, [5., 8.], scales=(.04, .1), offsets=(0., 0.), units=("reflectance",) * 2)
    stats = ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)
    assert stats["mean"] == pytest.approx(.6)
    assert stats["calibration"]["bands"]["nir"]["band_index"] == 2


def test_applied_marker_prevents_double_calibration(tmp_path):
    path = tmp_path / "applied.tif"
    write(path, [.2, .8], tags={"REFL_SCALE": ".0001", "REFL_OFFSET": "-.1", "REFL_APPLIED": "true"})
    stats = ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)
    assert stats["mean"] == pytest.approx(.6)
    assert stats["calibration"]["bands"]["red"]["applied"] is True


@pytest.mark.parametrize("scale,offset", [("nan", "0"), ("inf", "0"), ("0", "0"), ("-.1", "0"), (".1", "nan"), ("oops", "0")])
def test_invalid_declared_calibration_is_not_swallowed_by_ratio_fallback(tmp_path, scale, offset):
    path = tmp_path / "bad.tif"
    write(path, [1., 3.], tags={"REFL_SCALE": scale, "REFL_OFFSET": offset})
    with pytest.raises(ValueError, match="invalid_calibration"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_incomplete_declared_parameters_do_not_fall_back_to_sensor_defaults(tmp_path):
    path = tmp_path / "partial.tif"
    write(path, [2000., 4000.], tags={"SENSOR": "Sentinel-2B", "REFL_SCALE": ".0001"})
    with pytest.raises(ValueError, match="invalid_calibration"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_conflicting_declared_calibrations_are_rejected(tmp_path):
    path = tmp_path / "conflict.tif"
    write(path, [2000., 4000.], scales=(.01, .01), offsets=(0., 0.), units=("reflectance",) * 2,
          tags={"REFL_SCALE": ".0001", "REFL_OFFSET": "-.1"})
    with pytest.raises(ValueError, match="invalid_calibration"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_old_acquisition_date_is_not_processing_baseline_evidence(tmp_path):
    path = tmp_path / "reprocessed.tif"
    write(path, [2000., 4000.], tags={"SENSOR": "Sentinel-2B", "ACQUISITIONDATE": "2021-01-01"})
    with pytest.raises(StaleS2CompositeError, match="stale_s2_composite"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_landsat_name_does_not_prove_collection2_level2(tmp_path):
    path = tmp_path / "landsat.tif"
    write(path, [10000., 20000.], tags={"SENSOR": "Landsat 9"})
    with pytest.raises(ValueError, match="invalid_calibration"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_msavi_negative_radicand_is_nodata_not_fabricated_zero_root(tmp_path):
    path = tmp_path / "radicand.tif"
    write(path, [[.1, .1], [.1, .1], [-1., .2], [.2, .8]], units=("reflectance",) * 4)
    stats = spectral(input_path=str(path), output_dir=str(tmp_path / "out"), index_type="msavi")
    assert stats["mean"] == pytest.approx(.6)
    assert stats["valid_pixels"] == 1
    assert stats["nodata_pixels"] == 1
    assert stats["math_invalid_pixels"] == 1
    with rasterio.open(tmp_path / "out" / stats["output_tif"]) as src:
        assert np.isnan(src.read(1)[0, 0])


def test_overflowing_ratio_denominator_cannot_become_valid_zero(tmp_path):
    path = tmp_path / "overflow.tif"
    write(path, [3e38, 3e38], units=("reflectance",) * 2)
    with pytest.raises(AllPixelsInvalidError, match="all_pixels_invalid"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_water_threshold_uses_offset_corrected_ndwi(tmp_path):
    from compute_water_mask import compute as water
    path = tmp_path / "water_offset.tif"
    write(path, [1800., 1200.], tags={"REFL_SCALE": ".0001", "REFL_OFFSET": "-.1"})
    stats = water(input_path=str(path), output_dir=str(tmp_path / "out"), green_band=1, nir_band=2, threshold=.3)
    assert stats["water_pct"] == 100
    assert stats["calibration"]["bands"]["nir"]["offset"] == -.1


def test_water_quantitative_mask_requires_calibration(tmp_path):
    from compute_water_mask import compute as water
    path = tmp_path / "unknown_water.tif"
    write(path, [1800., 1200.])
    with pytest.raises(UncalibratedInputError, match="uncalibrated_input"):
        water(input_path=str(path), output_dir=str(tmp_path / "out"), green_band=1, nir_band=2)


@pytest.mark.parametrize("declared_index", [0, 1])
def test_partially_calibrated_required_bands_never_revert_to_raw(tmp_path, declared_index):
    path = tmp_path / "partial_group.tif"
    metas = [{}, {}]
    metas[declared_index] = {"REFL_SCALE": ".1", "REFL_OFFSET": "0"}
    write(path, [5., 8.], band_tags=metas)
    with pytest.raises(ValueError, match="invalid_calibration"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_all_quantity_sources_are_validated_not_just_the_first(tmp_path):
    path = tmp_path / "units.tif"
    write(path, [.2, .8], units=("kelvin", "reflectance"), tags={"REFL_QUANTITY": "reflectance"})
    with pytest.raises(ValueError, match="invalid_calibration"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_calibration_does_not_guess_band_indexes_from_dict_order(tmp_path):
    from raster_utils import calibrate_reflectance
    path = tmp_path / "indexes.tif"
    write(path, [.2, .8], units=("reflectance",) * 2)
    with rasterio.open(path) as src:
        for indexes in (None, {}):
            with pytest.raises(ValueError, match="invalid_calibration"):
                calibrate_reflectance(src, {"red": src.read(1), "nir": src.read(2)}, band_indexes=indexes)


def test_output_dtype_invalidity_and_statistics_agree(tmp_path):
    path = tmp_path / "huge_evi.tif"
    # The large first pixel has finite float64 EVI outside float32 storage range;
    # the second is the independently checked physical EVI 0.5/1.3.
    data = np.array([[[1e40 / 7.5, .08]], [[.09, .09]], [[0., .1]], [[1e40, .3]]], dtype="float64")
    with rasterio.open(path, "w", driver="GTiff", count=4, height=1, width=2, dtype="float64",
                       transform=from_origin(0, 1, 1, 1)) as dst:
        dst.write(data)
        dst.units = ("reflectance",) * 4
    stats = spectral(input_path=str(path), output_dir=str(tmp_path / "out"), index_type="evi")
    assert stats["valid_pixels"] == 1
    assert stats["math_invalid_pixels"] == 1
    assert stats["mean"] == pytest.approx(.5 / 1.3)
    with rasterio.open(tmp_path / "out" / stats["output_tif"]) as src:
        values = src.read(1)
        assert np.isnan(values[0, 0])
        assert values[0, 1] == pytest.approx(.5 / 1.3)


def test_raw_dn_units_with_declared_reflectance_parameters_are_supported(tmp_path):
    path = tmp_path / "dn_units.tif"
    write(path, [2000., 4000.], units=("dn",) * 2,
          tags={"REFL_SCALE": ".0001", "REFL_OFFSET": "-.1", "REFL_QUANTITY": "surface_reflectance", "REFL_APPLIED": "false"})
    stats = ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)
    assert stats["mean"] == pytest.approx(.5)
    assert stats["calibration"]["bands"]["red"]["input_quantity"] == "dn"


def test_applied_marker_cannot_disguise_input_dn_units(tmp_path):
    path = tmp_path / "dn_applied.tif"
    write(path, [2000., 4000.], units=("dn",) * 2,
          tags={"REFL_SCALE": ".0001", "REFL_OFFSET": "-.1", "REFL_APPLIED": "true"})
    with pytest.raises(ValueError, match="invalid_calibration"):
        ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)


def test_dn_with_gdal_parameters_and_reflectance_quantity_is_valid(tmp_path):
    path = tmp_path / "dn_gdal.tif"
    write(path, [5., 9.], units=("dn",) * 2, scales=(.1, .1), offsets=(-.1, -.1),
          tags={"REFL_QUANTITY": "surface_reflectance", "REFL_APPLIED": "false"})
    stats = ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)
    assert stats["mean"] == pytest.approx(1 / 3)


def test_dimensionless_unit_needs_separate_reflectance_evidence(tmp_path):
    path = tmp_path / "unitless.tif"
    write(path, [.2, .8], units=("1",) * 2, tags={"REFL_QUANTITY": "surface_reflectance"})
    stats = ndvi(input_path=str(path), output_dir=str(tmp_path / "out"), red_band=1, nir_band=2)
    assert stats["mean"] == pytest.approx(.6)
    assert stats["calibrated"] is True
    write(path, [.2, .8], units=("1",) * 2)
    stats = ndvi(input_path=str(path), output_dir=str(tmp_path / "unmarked"), red_band=1, nir_band=2)
    assert stats["calibrated"] is False
