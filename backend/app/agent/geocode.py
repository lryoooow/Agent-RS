"""
地理编码服务：坐标 → 地名文本

使用 Nominatim 逆地理编码 API，将经纬度转换为人类可读的位置描述。
"""

import asyncio
import logging
from collections import OrderedDict
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)

# Nominatim 请求需要 User-Agent（服务条款要求）
USER_AGENT = "Agent-RS/1.0 (Remote Sensing AI Agent)"
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
REQUEST_TIMEOUT = 1.5  # 秒
GEOCODE_CACHE_MAX_SIZE = 4096


class LocationInfo(NamedTuple):
    """位置信息"""
    display_name: str  # 完整地址文本
    lat: float
    lon: float
    zoom: int | None = None


_GEOCODE_CACHE: OrderedDict[str, LocationInfo] = OrderedDict()
_PREFETCH_TASKS: dict[str, asyncio.Task[None]] = {}
_client: httpx.AsyncClient | None = None


def _result_key(lat: float, lon: float) -> str:
    """坐标按约 1.1km 精度归一化，满足城市/区县级上下文。"""
    return f"{lat:.2f},{lon:.2f}"


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


async def reverse_geocode(
    lat: float,
    lon: float,
    zoom: int | None = None,
    *,
    language: str = "zh-CN",
) -> LocationInfo | None:
    """
    逆地理编码：坐标 → 地名

    Args:
        lat: 纬度
        lon: 经度
        zoom: 地图缩放级别（可选，用于上下文）
        language: 返回语言（默认中文）

    Returns:
        LocationInfo 或 None（请求失败时降级）
    """
    result_key = _result_key(lat, lon)
    cached = _GEOCODE_CACHE.get(result_key)
    if cached is not None:
        _GEOCODE_CACHE.move_to_end(result_key)
        return cached._replace(zoom=zoom)

    params = {
        "lat": f"{lat:.6f}",
        "lon": f"{lon:.6f}",
        "format": "json",
        "accept-language": language,
        "zoom": 14,  # 详细级别（城市/区县）
    }

    try:
        response = await _get_client().get(
            f"{NOMINATIM_BASE_URL}/reverse",
            params=params,
        )
        response.raise_for_status()
        display_name = response.json().get("display_name", "")
        if not display_name:
            logger.warning("Nominatim 返回空地名: %s", result_key)
            return None

        info = LocationInfo(
            display_name=display_name,
            lat=lat,
            lon=lon,
            zoom=zoom,
        )
        _GEOCODE_CACHE[result_key] = info
        _GEOCODE_CACHE.move_to_end(result_key)
        while len(_GEOCODE_CACHE) > GEOCODE_CACHE_MAX_SIZE:
            _GEOCODE_CACHE.popitem(last=False)
        return info
    except httpx.TimeoutException:
        logger.warning("Nominatim 请求超时: %s", result_key)
        return None
    except httpx.HTTPStatusError as e:
        logger.warning("Nominatim HTTP 错误 %s: %s", e.response.status_code, result_key)
        return None
    except Exception:
        logger.warning("reverse_geocode failed", exc_info=True)
        return None


def cached_location(
    lat: float,
    lon: float,
    zoom: int | None = None,
) -> LocationInfo | None:
    key = _result_key(lat, lon)
    cached = _GEOCODE_CACHE.get(key)
    if cached is not None:
        _GEOCODE_CACHE.move_to_end(key)
    return cached._replace(zoom=zoom) if cached is not None else None


def prefetch_location(lat: float, lon: float) -> None:
    key = _result_key(lat, lon)
    if key in _GEOCODE_CACHE or key in _PREFETCH_TASKS:
        return

    task = asyncio.create_task(_safe_fill(lat, lon))
    _PREFETCH_TASKS[key] = task

    def clear_finished(completed: asyncio.Task[None]) -> None:
        if _PREFETCH_TASKS.get(key) is completed:
            _PREFETCH_TASKS.pop(key, None)

    task.add_done_callback(clear_finished)


async def _safe_fill(lat: float, lon: float) -> None:
    try:
        await reverse_geocode(lat, lon)
    except Exception:
        logger.debug("后台逆地理编码失败", exc_info=True)


def format_location_context(location: LocationInfo | None, fallback_coords: tuple[float, float] | None = None) -> str:
    """
    格式化位置上下文文本

    Args:
        location: LocationInfo（可能为 None）
        fallback_coords: 降级坐标（lat, lon）

    Returns:
        格式化的位置描述文本
    """
    if location:
        parts = [f"用户当前查看的地图位置：{location.display_name}"]
        parts.append(f"中心坐标 [{location.lon:.4f}, {location.lat:.4f}]")
        if location.zoom is not None:
            parts.append(f"缩放级别 {location.zoom}")
        return "，".join(parts) + "。"

    if fallback_coords:
        lat, lon = fallback_coords
        return f"用户当前查看的地图中心坐标：[{lon:.4f}, {lat:.4f}]。"

    return ""
