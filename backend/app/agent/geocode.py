"""
地理编码服务：坐标 → 地名文本

使用 Nominatim 逆地理编码 API，将经纬度转换为人类可读的位置描述。
"""

import asyncio
import logging
import re
from collections import OrderedDict
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)

# Nominatim 请求需要 User-Agent（服务条款要求）
USER_AGENT = "Agent-RS/1.0 (Remote Sensing AI Agent)"
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
PHOTON_BASE_URL = "https://photon.komoot.io"
def _request_timeout() -> float:
    from app.core.settings import get_settings

    return get_settings().geocode_timeout_seconds


REQUEST_TIMEOUT = _request_timeout()  # 秒
GEOCODE_CACHE_MAX_SIZE = 4096
# 并发逆地理编码上限：Nominatim 用量策略 ~1 req/s，去重外的突发请求必须限流（O5）。
PREFETCH_MAX_CONCURRENT = 4


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


async def aclose_geocode_client() -> None:
    """lifespan 关闭时关闭模块全局 httpx 客户端，释放连接池（O5）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


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


_FORWARD_CACHE: OrderedDict[str, dict] = OrderedDict()

# 点状地名的目标缩放：城市及以下直接定心到中心点，**不**框行政边界。
# Nominatim 里「北京市」的 addresstype=city，但 bbox 是整个市域（含远郊山区，
# 跨约 2°）；前端对 bbox 走 fitBounds，把这个框整个装进视野只会把视角拉远——
# 用户说"去北京"要的是城市核心区，不是"看清北京市界"。
_POINT_PLACE_ZOOM: dict[str, int] = {
    "city": 11,
    "town": 13,
    "village": 14,
    "hamlet": 15,
    "suburb": 13,
    "quarter": 13,
    "neighbourhood": 14,
    "borough": 12,
    "city_district": 12,
}


def _zoom_for_bbox(bbox: list[str] | None) -> int:
    """据 Nominatim boundingbox 粗估缩放级别；无 bbox 给城市级默认。"""
    if not bbox or len(bbox) != 4:
        return 11
    try:
        south, north, west, east = (float(x) for x in bbox)
    except (TypeError, ValueError):
        return 11
    span = max(abs(north - south), abs(east - west))
    if span <= 0.02:
        return 14
    if span <= 0.1:
        return 12
    if span <= 1.0:
        return 9
    if span <= 10:
        return 6
    return 4


async def forward_geocode(query: str) -> dict | None:
    """正向地理编码：地名 → {display_name, center:[lon,lat], bbox?, zoom}。

    供「对话控图」和影像检索共用。Photon 是主服务，Nominatim 是备用；
    任一公共服务暂时不可达时，另一条链路仍可完成定位。
    """
    q = (query or "").strip()
    if not q:
        return None
    key = q.lower()
    cached = _FORWARD_CACHE.get(key)
    if cached is not None:
        _FORWARD_CACHE.move_to_end(key)
        return cached
    result = await _forward_geocode_photon(q)
    if result is None:
        result = await _forward_geocode_nominatim(q)
    if result is None:
        logger.warning("All forward geocoders failed or returned no result: %s", q)
        return None
    _FORWARD_CACHE[key] = result
    _FORWARD_CACHE.move_to_end(key)
    while len(_FORWARD_CACHE) > GEOCODE_CACHE_MAX_SIZE:
        _FORWARD_CACHE.popitem(last=False)
    return result


def _display_name_from_photon(properties: dict, fallback: str) -> str:
    parts: list[str] = []
    for field in ("name", "district", "city", "county", "state", "country"):
        value = str(properties.get(field) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return "，".join(parts) or fallback


async def _forward_geocode_photon(query: str) -> dict | None:
    features: list[dict] = []
    try:
        for provider_query in _photon_query_variants(query):
            resp = await _get_client().get(
                f"{PHOTON_BASE_URL}/api/",
                params={"q": provider_query, "limit": 6},
            )
            resp.raise_for_status()
            payload = resp.json()
            batch = payload.get("features") if isinstance(payload, dict) else None
            if isinstance(batch, list):
                features.extend(item for item in batch if isinstance(item, dict))
            if any(_photon_place_type(item) in {"city", "district", "county", "state"} for item in features):
                break
        if not features:
            return None
        feature = max(features, key=lambda item: _photon_rank(item, query))
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(coords, list) or len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
    except Exception:
        logger.warning("Photon forward geocode failed: %s", query, exc_info=True)
        return None

    result: dict = {
        "display_name": _display_name_from_photon(properties, query),
        "center": [lon, lat],
        "provider": "photon",
    }
    place_type = str(properties.get("type") or properties.get("osm_value") or "").lower()
    if place_type in _POINT_PLACE_ZOOM:
        result["zoom"] = _POINT_PLACE_ZOOM[place_type]
        return result

    extent = properties.get("extent")
    if isinstance(extent, list) and len(extent) == 4:
        try:
            west, y1, east, y2 = (float(value) for value in extent)
            south, north = sorted((y1, y2))
            if west < east and south < north:
                result["bbox"] = [[west, south], [east, north]]
                result["zoom"] = _zoom_for_map_bbox(west, south, east, north)
                return result
        except (TypeError, ValueError):
            pass
    result["zoom"] = 11
    return result


def _photon_query_variants(query: str) -> list[str]:
    compact = "".join(query.split())
    variants: list[str] = []
    province_tail = re.search(r"(?:省|自治区|特别行政区)(.+)$", compact)
    if province_tail:
        variants.append(province_tail.group(1))
    variants.append(query)
    if re.fullmatch(r"[\u3400-\u9fff]{4,8}", compact) and not compact.endswith(("省", "市", "区", "县", "州", "盟")):
        for split in range(2, len(compact) - 1):
            variants.append(f"{compact[split:]}区 {compact[:split]}市")
    return list(dict.fromkeys(variants))


def _photon_place_type(feature: dict) -> str:
    properties = feature.get("properties") or {}
    return str(properties.get("type") or properties.get("osm_value") or "").lower() if isinstance(properties, dict) else ""


def _photon_rank(feature: dict, query: str) -> tuple[int, int]:
    properties = feature.get("properties") or {}
    if not isinstance(properties, dict):
        return (0, 0)
    place_type = _photon_place_type(feature)
    type_score = {
        "city": 120,
        "district": 115,
        "county": 110,
        "state": 105,
        "town": 100,
        "village": 95,
        "river": 90,
        "street": 85,
        "other": 60,
        "locality": 35,
        "house": 10,
    }.get(place_type, 50)
    compact_query = re.sub(r"[\s省市区县州盟自治区特别行政]", "", query)
    match_score = 0
    for field, weight in (("name", 50), ("city", 30), ("district", 25), ("state", 15)):
        value = re.sub(r"[\s省市区县州盟自治区特别行政]", "", str(properties.get(field) or ""))
        if value and (value in compact_query or compact_query in value):
            match_score += weight
    return (type_score + match_score, -len(str(properties.get("name") or "")))


async def _forward_geocode_nominatim(query: str) -> dict | None:
    try:
        resp = await _get_client().get(
            f"{NOMINATIM_BASE_URL}/search",
            params={"q": query, "format": "json", "limit": 1, "accept-language": "zh-CN"},
        )
        resp.raise_for_status()
        items = resp.json()
    except Exception:
        logger.warning("Nominatim forward geocode failed: %s", query, exc_info=True)
        return None
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    # bbox 先解析成 MapLibre 形状 [[west,south],[east,north]]；
    # 是否随结果下发由地名类型决定（见 _POINT_PLACE_ZOOM 的说明）。
    bbox_parsed = None
    bbox = item.get("boundingbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            south, north, west, east = (float(x) for x in bbox)
            bbox_parsed = [[west, south], [east, north]]
        except (TypeError, ValueError):
            pass

    result: dict = {
        "display_name": item.get("display_name") or query,
        "center": [lon, lat],
        "provider": "nominatim",
    }
    addresstype = str(item.get("addresstype") or "").lower()
    if addresstype in _POINT_PLACE_ZOOM:
        # 点状地名：定心 + 城市级缩放，不下发 bbox（前端见 bbox 会改走 fitBounds）。
        result["zoom"] = _POINT_PLACE_ZOOM[addresstype]
    else:
        result["zoom"] = _zoom_for_bbox(bbox)
        if bbox_parsed is not None:
            result["bbox"] = bbox_parsed
    return result


def _zoom_for_map_bbox(west: float, south: float, east: float, north: float) -> int:
    return _zoom_for_bbox([str(south), str(north), str(west), str(east)])


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
    # O5：限并发——超出上限的突发去重坐标不再发起 prefetch，避免把 Nominatim 打到限流/封禁。
    if len(_PREFETCH_TASKS) >= PREFETCH_MAX_CONCURRENT:
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
