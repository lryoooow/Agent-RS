from . import build_domain

RASTER = ("raster_inspect", "calculate_ndvi", "calculate_spectral_index", "render_band_composite",
          "clip_reproject_raster", "cloud_shadow_mask", "extract_water_mask")


def build_raster_mcp():
    return build_domain("Agent-RS Raster", RASTER)
