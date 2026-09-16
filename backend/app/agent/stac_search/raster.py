"""COG 窗口读取：预览 PNG 生成与多波段 GeoTIFF 合成。

所有读取都发生在服务端：远程 COG 经 /vsicurl + HTTP Range 请求按需取块，
预览读降采样（秒级），合成按窗口尺寸封顶防止流量失控。Planetary Computer
的资产在打开前做匿名 SAS 签名（sources.signed_href），签名只在这一层
出现，不回传给任何调用方。
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.agent.stac_search.model import SceneRecord
from app.agent.stac_search.sources import signed_href
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class SceneRasterError(Exception):
    """远程 COG 打不开 / 读不出来。调用方应如实告知用户，不要编造。"""


def _gdal_env() -> dict[str, str]:
    settings = get_settings()
    env = {
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_TIMEOUT": str(int(settings.stac_timeout_seconds)),
        # 只放行 tif 后缀，避免 vsicurl 误抓目录页。
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    }
    if settings.stac_http_proxy:
        env["GDAL_HTTP_PROXY"] = settings.stac_http_proxy
    return env


def _open_path(href: str) -> str:
    """远程 COG 经 /vsicurl；本地路径（测试用合成文件）直接打开。"""
    return f"/vsicurl/{href}" if href.startswith(("http://", "https://")) else href


def _band_href(record: SceneRecord, role: str) -> str:
    href = record.band_assets.get(role)
    if not href:
        raise SceneRasterError(f"场景 {record.display_name} 缺少 {role} 波段资产")
    return signed_href(href, record.asset_sign_info.get(role))


def _stretch_to_byte(values: np.ndarray) -> np.ndarray:
    """分位数拉伸到 uint8：远程影像的量纲各不相同，拉伸只用于视觉呈现。"""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [2, 98])
    if high <= low:
        return np.zeros(values.shape, dtype=np.uint8)
    scaled = (np.clip(values.astype(np.float32), low, high) - low) / (high - low)
    return (scaled * 255).astype(np.uint8)


def render_scene_preview(record: SceneRecord, out_path: Path) -> Path:
    """RGB 三波段降采样预览 PNG。

    读的是 COG 的降采样视图（out_shape），不拉全图；out_path 由调用方放到
    per-user 缓存目录，命中已存在文件时直接复用。
    """
    import rasterio
    from PIL import Image

    if out_path.exists():
        return out_path

    size = get_settings().agent_scene_preview_size
    roles = record.preview_roles
    channels: list[np.ndarray] = []
    with rasterio.Env(**_gdal_env()):
        for role in roles:
            href = _band_href(record, role)
            try:
                with rasterio.open(_open_path(href)) as src:
                    shape = (
                        max(1, int(src.height * size / max(src.width, src.height))),
                        max(1, int(src.width * size / max(src.width, src.height))),
                    )
                    channels.append(src.read(1, out_shape=shape).astype(np.float32))
            except Exception as exc:
                raise SceneRasterError(
                    f"读取 {record.display_name} 的 {role} 波段失败：{type(exc).__name__}"
                ) from exc

    rgb = np.dstack([_stretch_to_byte(channel) for channel in channels])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(out_path, optimize=True)
    return out_path


def _apply_reflectance(record: SceneRecord, band: np.ndarray) -> np.ndarray:
    """Landsat SR 的偏置量化必须转真反射率，否则比值类指数（NDVI 等）失真。

    S2 L2A 的 DN/10000 是纯线性缩放（无偏置），比值不变，保持整型原值即可。
    """
    if record.reflectance_scale is None or record.reflectance_offset is None:
        return band
    converted = band.astype(np.float32) * record.reflectance_scale + record.reflectance_offset
    return np.where(band == 0, 0.0, converted)  # 0 是 nodata，保持 0 不参与拉伸


def compose_scene_tif(
    record: SceneRecord,
    out_path: Path,
    *,
    bbox: list[float] | None = None,
) -> dict:
    """合成多波段 GeoTIFF（下载/导入共用），返回附注元数据。

    - 波段顺序按角色字母序（blue/green/nir/red/swir），波段描述写入文件——
      Phase 2 的 `_extract_metadata` 会自然读到并生成 band_roles；
    - bbox（EPSG:4326）可裁剪到关注区；窗口像素封顶（超出按比例降采样）；
    - 各波段网格不齐（S2 的 swir 是 20m、红光是 10m）：统一按**地理范围**
      给每个波段算各自的像素窗口，输出网格由范围重建，不做像素级平移；
    - Landsat 转真反射率（float32），S2 保持原始 DN。
    """
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import transform_bounds

    if out_path.exists():
        raise FileExistsError(f"目标文件已存在：{out_path}")

    max_pixels = get_settings().agent_scene_window_max_pixels
    roles = sorted(record.band_assets)
    # 以 red 波段的栅格为几何基准（定 CRS 与地理范围）。
    base_href = _band_href(record, "red")

    with rasterio.Env(**_gdal_env()):
        try:
            with rasterio.open(_open_path(base_href)) as base:
                crs = base.crs
                if bbox is not None:
                    left, bottom, right, top = transform_bounds(
                        "EPSG:4326", crs, *bbox, densify_pts=21
                    )
                else:
                    left, bottom, right, top = base.bounds
                # 输出分辨率不超过基准波段的 native 分辨率。
                left, bottom, right, top = max(left, base.bounds.left), max(bottom, base.bounds.bottom), min(right, base.bounds.right), min(top, base.bounds.top)
                if left >= right or bottom >= top:
                    raise SceneRasterError("所选范围与场景不相交")
                native_size = list(base.res)
                native_span = max((right-left)/abs(base.transform.a), (top-bottom)/abs(base.transform.e))
                scale = min(1.0, max_pixels / max(native_span, 1))
                out_width = max(1, min(int((right - left) / abs(base.transform.a) * scale) or 1, max_pixels))
                out_height = max(1, min(int((top - bottom) / abs(base.transform.e) * scale) or 1, max_pixels))
                transform = from_bounds(left, bottom, right, top, out_width, out_height)

                bands: list[np.ndarray] = []
                for role in roles:
                    href = base_href if role == "red" else _band_href(record, role)
                    with rasterio.open(_open_path(href)) as src:
                        with WarpedVRT(src, crs=crs, transform=transform, width=out_width, height=out_height,
                                       src_nodata=src.nodata if src.nodata is not None else 0,
                                       nodata=float("nan"), dtype="float32", resampling=Resampling.bilinear) as aligned:
                            data = aligned.read(1)
                    bands.append(_apply_reflectance(record, data))
        except SceneRasterError:
            raise
        except Exception as exc:
            raise SceneRasterError(
                f"读取 {record.display_name} 失败：{type(exc).__name__}"
            ) from exc

    transform = from_bounds(left, bottom, right, top, out_width, out_height)
    final_dtype = bands[0].dtype
    profile = {
        "driver": "GTiff",
        "width": out_width,
        "height": out_height,
        "count": len(bands),
        "dtype": final_dtype.name,
        "crs": crs,
        "transform": transform,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
        "nodata": float("nan"),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        for index, (role, data) in enumerate(zip(roles, bands), start=1):
            dst.write(data, index)
            dst.set_band_description(index, role)
        dst.update_tags(
            NATIVE_PIXEL_SIZE=",".join(map(str, native_size)),
            SENSOR=record.satellite,
            ACQUISITIONDATE=record.datetime,
        )

    return {
        "native_pixel_size": native_size,
        "band_roles": record.band_roles,
        "band_roles_source": "stac_assets",
        "sensor": record.satellite,
        "acquired_at": record.datetime,
        "roles": roles,
        "width": out_width,
        "height": out_height,
        "dtype": final_dtype.name,
    }
