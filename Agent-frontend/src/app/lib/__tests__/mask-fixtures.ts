export const maskPayload = (type = "cloud_mask") => ({
  type, imagery_id: "image", result_url: `/api/imagery/image/results/${type}.png`,
  bounds: [114, 24, 115, 25],
  stats: type === "water_mask" ? {
    water_pct: 60, non_water_pct: 30, nodata_pct: 10,
    water_valid_pct: 66.67, total_pixels: 100, valid_pixels: 90, nodata_pixels: 10,
    percentage_denominator: "total_pixels", threshold_method: "fixed_ndwi", threshold_value: 0,
    calibrated: true, calibration: { method: "declared_reflectance", method_version: "reflectance-v2", bands: {
      green: { band_index: 2, scale: 0.0001, offset: -0.1, source: "STAC", applied: true, input_applied: false, quantity: "reflectance" },
    } }, resolved_bands: { green: 2, nir: 4 },
  } : {
    method: "quality_mask", method_validation: "product_flags", quality_type: "sentinel2_scl",
    quality_source: "sentinel2", quality_sensor: "Sentinel-2", quality_item_id: "scene",
    total_pixels: 100, valid_pixels: 90, nodata_pixels: 10, percentage_denominator: "total_pixels",
    cloud_pct: 20, shadow_pct: 10, clear_pct: 30, unknown_pct: 10, snow_pct: 10, terrain_shadow_pct: 10, nodata_pct: 10,
  },
});
