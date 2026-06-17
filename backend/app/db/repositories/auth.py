"""Facade: dispatches to the active storage backend (_pg or _sqlite).

Call sites keep importing `from app.db.repositories.auth import ...` unchanged;
this module re-exports the implementation matching STORAGE_BACKEND.
"""
from app.core.settings import get_settings

if get_settings().resolved_storage_backend == "sqlite":
    from app.db.repositories._sqlite.auth import *  # noqa: F401,F403
else:
    from app.db.repositories._pg.auth import *  # noqa: F401,F403
