"""免账号卫星影像检索数据层（Phase 7）。

对外只暴露三样东西：
- `search_scenes()`：按区域/时间/云量搜统一格式的场景（EarthSearch +
  Planetary Computer 双源，全部免账号，已在目标网络实测）
- `render_scene_preview()`：服务端从真实 COG 波段生成预览 PNG
- `compose_scene_tif()`：多波段 GeoTIFF 合成（下载/导入用，含波段语义）

层级约定（防泄漏）：
- 资产 URL 与 SAS 令牌只存在服务端内存（场景缓存按 user_id 隔离），
  不进提示词、日志或数据库；给模型/前端的只有场景 key 与摘要。
- 出网端点硬编码白名单（EarthSearch / Planetary Computer），无任何
  客户端可控 URL，天然无 SSRF 面。
"""

from app.agent.stac_search.model import SceneRecord
from app.agent.stac_search.sources import search_scenes

__all__ = ["SceneRecord", "search_scenes"]
