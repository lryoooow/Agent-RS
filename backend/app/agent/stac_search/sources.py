"""免账号 STAC 双源适配：EarthSearch（Sentinel-2）+ Planetary Computer（Landsat）。

两个端点都在出网白名单里硬编码，调用方（工具/API 层）不提供任何 URL，
因此这里不存在 SSRF 面。全部匿名访问：EarthSearch 的 COG 资产直读；
Planetary Computer 的资产读取前做匿名 SAS 签名（签名端点同样免账号）。

可用性约定：`source="auto"` 时两源并发，单源失败只告警并返回另一源的
结果（响应里注明降级）；显式指定单源时失败抛 StacSearchError。
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.agent.stac_search.model import SceneRecord, scene_key
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

EARTHSEARCH_ENDPOINT = "https://earth-search.aws.element84.com/v1"
PLANETARY_COMPUTER_ENDPOINT = "https://planetarycomputer.microsoft.com/api/stac/v1"
_PC_SAS_ENDPOINT = "https://planetarycomputer.microsoft.com/api/sas/v1"


class StacSearchError(Exception):
    """两个数据源都不可用，或显式指定的数据源失败。"""


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    endpoint: str
    collection: str
    satellite_default: str
    resolution_m: float
    # 角色 → 候选 asset key（按序取第一个存在的）。不同源对 NIR/SWIR 的
    # asset 命名不一致（S2 有 10m 的 "nir"，Landsat 只有 "nir08"）。
    role_assets: dict[str, tuple[str, ...]]
    # Planetary Computer 的资产在 Azure Blob 上，读取前需要匿名 SAS 签名。
    requires_sas: bool = False
    # Landsat C2 L2 表观反射率的量化参数：ρ = DN * scale + offset。
    reflectance_scale: float | None = None
    reflectance_offset: float | None = None
    # True：compose 时把 DN 换算成反射率写盘（Landsat 历史行为）；
    # False：compose 只写 REFL_* 标签不改像元（S2 路径，见 model.SceneRecord）。
    apply_reflectance_at_compose: bool = True


_SOURCES: dict[str, SourceSpec] = {
    "sentinel2": SourceSpec(
        source_id="sentinel2",
        endpoint=EARTHSEARCH_ENDPOINT,
        collection="sentinel-2-c1-l2a",
        satellite_default="Sentinel-2",
        resolution_m=10.0,
        role_assets={
            "blue": ("blue",),
            "green": ("green",),
            "red": ("red",),
            "nir": ("nir", "nir08"),
            "swir1": ("swir16",),
            "swir2": ("swir22",),
        },
        # S2 c1-l2a 条目自带 raster:bands（scale 0.0001 / offset -0.1，
        # PB>=04.00 的 BOA offset），由 record_from_item 逐条读取；compose
        # 不改像元，只写 REFL_* 标签（2026-10-07 D3 核实，详见 raster_utils）。
        apply_reflectance_at_compose=False,
    ),
    "landsat": SourceSpec(
        source_id="landsat",
        endpoint=PLANETARY_COMPUTER_ENDPOINT,
        collection="landsat-c2-l2",
        satellite_default="Landsat",
        resolution_m=30.0,
        role_assets={
            "blue": ("blue",),
            "green": ("green",),
            "red": ("red",),
            "nir": ("nir08", "nir"),
            "swir1": ("swir16",),
            "swir2": ("swir22",),
        },
        requires_sas=True,
        reflectance_scale=2.75e-05,
        reflectance_offset=-0.2,
    ),
}

_PLATFORM_LABELS = {
    "sentinel-2a": "Sentinel-2A",
    "sentinel-2b": "Sentinel-2B",
    "sentinel-2c": "Sentinel-2C",
    "landsat-4": "Landsat 4",
    "landsat-5": "Landsat 5",
    "landsat-7": "Landsat 7",
    "landsat-8": "Landsat 8",
    "landsat-9": "Landsat 9",
}

# pystac-client 的 Client 是同步的且线程安全可复用，按端点缓存。
_CLIENTS: dict[str, Any] = {}


def _get_client(endpoint: str):
    if endpoint not in _CLIENTS:
        from pystac_client import Client

        _CLIENTS[endpoint] = Client.open(endpoint)
    return _CLIENTS[endpoint]


def _satellite_label(spec: SourceSpec, properties: dict) -> str:
    platform = str(properties.get("platform") or "").strip().lower()
    return _PLATFORM_LABELS.get(platform, spec.satellite_default)


def _raster_band_scale_offset(asset: Any) -> tuple[float | None, float | None]:
    """从 STAC asset 的 raster:bands 扩展读 (scale, offset)。

    c1-l2a 条目每个光学波段资产都带 {scale: 0.0001, offset: -0.1}
    （PB>=04.00 的 BOA offset，2026-10-07 实测核实）。字段缺失/非法时
    返回 (None, None)，调用方回落源规格默认。
    """
    extra = getattr(asset, "extra_fields", {}) or {}
    entries = extra.get("raster:bands") or []
    if not entries:
        return None, None
    entry = entries[0]
    if "scale" not in entry and "offset" not in entry:
        return None, None
    try:
        scale, offset = float(entry["scale"]), float(entry["offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StacSearchError("STAC 资产定标参数缺失或非法，无法可靠计算反射率。") from exc
    if not math.isfinite(scale) or not math.isfinite(offset) or scale <= 0:
        raise StacSearchError("STAC 资产定标参数必须有限且 scale>0。")
    return scale, offset


def record_from_item(spec: SourceSpec, item: Any) -> SceneRecord | None:
    """pystac Item → 统一 SceneRecord；缺核心资产（无 RGB）时返回 None。"""
    properties: dict = getattr(item, "properties", {}) or {}
    band_assets: dict[str, str] = {}
    sign_info: dict[str, tuple[str, str]] = {}
    assets = getattr(item, "assets", {}) or {}
    # 反射率定标参数：Landsat 用源规格（固定量化参数）；S2 从条目资产
    # raster:bands 逐条读取（无该元数据时保持 None → 合成 DN、定标回落
    # offset=0，与历史行为一致）。
    band_calibration: dict[str, dict] = {}
    for role, candidates in spec.role_assets.items():
        for asset_key in candidates:
            asset = assets.get(asset_key)
            href = getattr(asset, "href", None) if asset is not None else None
            if href:
                band_assets[role] = href
                scale, offset = _raster_band_scale_offset(asset)
                calibration_source = "stac:raster:bands"
                if scale is None and spec.reflectance_scale is not None:
                    scale, offset = spec.reflectance_scale, spec.reflectance_offset
                    calibration_source = f"source_spec:{spec.collection}"
                if scale is not None and offset is not None:
                    band_calibration[role] = {"scale": scale, "offset": offset,
                        "source": calibration_source, "quantity": "surface_reflectance"}
                if spec.requires_sas:
                    extra = getattr(asset, "extra_fields", {}) or {}
                    account = extra.get("msft:storage_account")
                    container = extra.get("msft:container")
                    if account and container:
                        sign_info[role] = (account, container)
                    else:
                        # 扩展字段缺失时从 blob URL 推断（账号=主机首段，容器=路径首段）。
                        sign_info[role] = _sign_target_from_href(href) or ("", "")
                break
    if not all(r in band_assets for r in ("blue", "green", "red")):
        return None

    acquired = getattr(item, "datetime", None) or properties.get("start_datetime")
    if acquired is None:
        return None
    cloud = properties.get("eo:cloud_cover")
    bbox = list(item.bbox or [])[:4]
    if len(bbox) != 4:
        return None

    quality_type, quality_key = ("sentinel2_scl", "scl") if spec.collection == "sentinel-2-c1-l2a" else ("landsat_c2_qa_pixel", "qa_pixel")
    quality_assets: dict[str, str] = {}
    quality_sign_info: dict[str, tuple[str, str]] = {}
    quality_asset = assets.get(quality_key)
    quality_href = getattr(quality_asset, "href", None)
    if quality_href:
        quality_assets[quality_type] = quality_href
        if spec.requires_sas:
            extra = getattr(quality_asset, "extra_fields", {}) or {}
            target = (extra.get("msft:storage_account"), extra.get("msft:container"))
            quality_sign_info[quality_type] = target if all(target) else (_sign_target_from_href(quality_href) or ("", ""))
    common_parameters = {(c["scale"], c["offset"]) for c in band_calibration.values()}
    common = next(iter(common_parameters)) if len(common_parameters) == 1 and len(band_calibration) == len(band_assets) else (None, None)
    return SceneRecord(
        key=scene_key(spec.source_id, item.id),
        source=spec.source_id,
        item_id=item.id,
        collection=spec.collection,
        satellite=_satellite_label(spec, properties),
        datetime=str(acquired),
        cloud_cover=round(float(cloud), 2) if cloud is not None else None,
        bbox=[float(x) for x in bbox],
        resolution_m=spec.resolution_m,
        band_assets=band_assets,
        display_name=f"{_satellite_label(spec, properties)} {item.id}",
        reflectance_scale=common[0],
        reflectance_offset=common[1],
        band_calibration=band_calibration,
        quality_assets=quality_assets,
        quality_sign_info=quality_sign_info,
        reflectance_applied_at_compose=spec.apply_reflectance_at_compose,
        asset_sign_info=sign_info,
    )


def _search_source(
    spec: SourceSpec,
    *,
    bbox: list[float],
    date_range: str,
    cloud_max: float | None,
    limit: int,
) -> list[SceneRecord]:
    """同步搜索（在线程池里跑）：pystac-client 是同步库。"""
    client = _get_client(spec.endpoint)
    query = {"eo:cloud_cover": {"lte": cloud_max}} if cloud_max is not None else None
    search = client.search(
        collections=[spec.collection],
        bbox=bbox,
        datetime=date_range,
        query=query,
        max_items=limit,
    )
    records = []
    for item in search.items():
        record = record_from_item(spec, item)
        if record is not None:
            records.append(record)
    return records


async def search_scenes(
    *,
    bbox: list[float],
    start_date: str | None = None,
    end_date: str | None = None,
    cloud_max: float | None = None,
    source: str = "auto",
    limit: int = 8,
) -> tuple[list[SceneRecord], list[str]]:
    """按区域搜场景，返回 (结果, 降级说明)。

    bbox 为 EPSG:4326 的 [w, s, e, n]；auto 双源并发取并集按时间倒序，
    单源失败不拖垮整体（可用性优先，降级说明返回给调用方展示）。
    """
    if len(bbox) != 4:
        raise StacSearchError("检索范围必须是 [west, south, east, north] 四元组")
    limit = max(1, min(limit, 20))

    parts = []
    if start_date:
        parts.append(str(start_date))
    if end_date:
        parts.append(str(end_date))
    date_range = "/".join(parts) if parts else None

    if source == "auto":
        specs = [_SOURCES["sentinel2"], _SOURCES["landsat"]]
    elif source in _SOURCES:
        specs = [_SOURCES[source]]
    else:
        raise StacSearchError(f"未知数据源 {source!r}，可选：auto、{sorted(_SOURCES)}")

    timeout = get_settings().stac_timeout_seconds
    results = await asyncio.gather(
        *(
            asyncio.wait_for(
                asyncio.to_thread(
                    _search_source,
                    spec,
                    bbox=bbox,
                    date_range=date_range,
                    cloud_max=cloud_max,
                    limit=limit,
                ),
                timeout=timeout,
            )
            for spec in specs
        ),
        return_exceptions=True,
    )

    records: list[SceneRecord] = []
    notes: list[str] = []
    for spec, result in zip(specs, results):
        if isinstance(result, Exception):
            logger.warning(
                "影像检索源 %s 失败（已降级）：%s", spec.source_id, type(result).__name__
            )
            notes.append(f"{spec.satellite_default}源暂时不可用")
        else:
            records.extend(result)
    if not records and notes:
        raise StacSearchError("；".join(notes))
    records.sort(key=lambda r: r.datetime, reverse=True)
    return records[:limit], notes


# ────────────────────── Planetary Computer 匿名 SAS 签名 ──────────────────────
# 签名端点免账号（匿名限流足够本地开发用）。令牌按 (存储账号, 容器) 粒度缓存，
# 快过期才重取。只在本模块与 raster 读取线程内使用，不外泄。

_SAS_TOKENS: dict[tuple[str, str], tuple[str, float]] = {}


def _pc_account_from_href(href: str) -> str | None:
    host = urlparse(href).hostname or ""
    if not host.endswith(".blob.core.windows.net"):
        return None
    return host.split(".")[0]


def _sign_target_from_href(href: str) -> tuple[str, str] | None:
    """从 blob URL 推断 (storage_account, container)。

    账号是主机名首段；容器是**路径首段**（如
    landsateuwest.blob.core.windows.net/**landsat-c2**/level-2/...）。
    只用账号名当容器会 404——令牌是按 (账号, 容器) 两段签发的。
    """
    account = _pc_account_from_href(href)
    if account is None:
        return None
    parts = [p for p in urlparse(href).path.split("/") if p]
    return (account, parts[0] if parts else account)


def signed_href(href: str, sign_target: tuple[str, str] | None = None) -> str:
    """给 Azure Blob 资产 href 追加匿名 SAS 令牌；非 PC 资产原样返回。

    sign_target 是 (storage_account, container)——令牌端点是两段路径
    /token/{account}/{container}，只有容器名会 404。缺扩展字段时退化为
    主机名首段（account=container），覆盖多数单容器数据集。

    同步实现：调用方（raster 合成）运行在线程池里。令牌过期时间取响应的
    msft:expiry 并提前 5 分钟刷新，避免读到一半过期。
    """
    target = sign_target
    if target is None or not target[0]:
        target = _sign_target_from_href(href)
        if target is None:
            return href

    now = time.monotonic()
    cached = _SAS_TOKENS.get(target)
    if cached and cached[1] > now:
        token = cached[0]
    else:
        account, container = target
        response = httpx.get(
            f"{_PC_SAS_ENDPOINT}/token/{account}/{container}",
            timeout=get_settings().stac_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload["token"]
        # msft:expiry 是 ISO 时间串（如 2026-09-13T15:21:25Z），提前 5 分钟刷新。
        ttl = 600.0
        raw_expiry = payload.get("msft:expiry")
        if raw_expiry:
            try:
                from datetime import datetime

                expires_at = datetime.fromisoformat(
                    str(raw_expiry).replace("Z", "+00:00")
                ).timestamp()
                ttl = max(60.0, expires_at - time.time() - 300)
            except ValueError:
                pass
        _SAS_TOKENS[target] = (token, now + ttl)
    separator = "&" if "?" in href else "?"
    return f"{href}{separator}{token}"


def source_spec(source_id: str) -> SourceSpec | None:
    return _SOURCES.get(source_id)
