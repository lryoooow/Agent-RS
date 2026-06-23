"""Repository facade: re-exports the PostgreSQL implementation.

Call sites keep importing `from app.db.repositories.invite import ...` unchanged.
仅 PostgreSQL；保留这层薄转发，调用方 import 路径稳定（与 auth/message 等同范式）。
"""
from app.db.repositories._pg.invite import *  # noqa: F401,F403
