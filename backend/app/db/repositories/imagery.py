"""Repository facade: re-exports the PostgreSQL implementation。

调用方保持 `from app.db.repositories.imagery import ...` 不变；SQLite 后端已退役。
"""
from app.db.repositories._pg.imagery import *  # noqa: F401,F403
