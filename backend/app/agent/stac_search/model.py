"""统一场景模型：两个免账号数据源（EarthSearch / Planetary Computer）汇成一种形状。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SceneRecord:
    """一景可预览/下载/导入的卫星影像。

    band_assets 的 key 是光谱角色（blue/green/red/nir/swir），value 是
    STAC asset 的原始 href。Planetary Computer 的 href 在读取时才做匿名
    SAS 签名——签名令牌同样只存在服务端。
    """

    key: str
    source: str  # "earthsearch" | "planetary_computer"
    item_id: str
    collection: str
    satellite: str
    datetime: str  # ISO 8601
    cloud_cover: float | None
    bbox: list[float]  # [west, south, east, north]，EPSG:4326
    resolution_m: float | None
    band_assets: dict[str, str]
    display_name: str
    # 渲染预览所需的 RGB 三波段（角色名）。
    preview_roles: tuple[str, str, str] = ("red", "green", "blue")
    # Landsat L2 SR 是带偏置的整数量化（DN = (ρ + 0.2) / 0.0000275），
    # 比值类指数必须先转反射率；S2 L2A 的 /10000 是纯线性缩放，比值不变。
    reflectance_scale: float | None = field(default=None)
    reflectance_offset: float | None = field(default=None)
    # Planetary Computer 资产的 SAS 签名目标：role -> (storage_account, container)。
    # 来自 STAC 条目的 msft:storage_account / msft:container 扩展字段；
    # 令牌端点是两段路径 /token/{account}/{container}，只有容器名会 404。
    asset_sign_info: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def band_roles(self) -> dict[str, int]:
        """角色 → 波段号（1 基）。合成 TIF 的波段顺序按 sorted(band_assets)。"""
        return {role: index for index, role in enumerate(sorted(self.band_assets), start=1)}


def scene_key(source: str, item_id: str) -> str:
    """场景在缓存与 API 中的句柄：源+条目 ID 的短哈希。

    12 位十六进制与影像 ID 同形（`^[a-f0-9]{12}$`），但命名空间独立，
    不会与上传影像混淆。
    """
    digest = hashlib.sha1(f"{source}:{item_id}".encode("utf-8")).hexdigest()
    return digest[:12]
