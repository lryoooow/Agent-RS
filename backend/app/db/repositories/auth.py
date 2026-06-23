"""Repository facade: re-exports the PostgreSQL implementation.

Call sites keep importing `from app.db.repositories.auth import ...` unchanged.
SQLite 后端已退役，本项目仅 PostgreSQL；保留这层薄转发，调用方 import 路径稳定。
"""
from app.db.repositories._pg.auth import *  # noqa: F401,F403
