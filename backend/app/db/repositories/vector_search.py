"""Facade: dispatches to the active storage backend (_pg or _sqlite)."""
from app.core.settings import get_settings

if get_settings().resolved_storage_backend == "sqlite":
    from app.db.repositories._sqlite.vector_search import *  # noqa: F401,F403
else:
    from app.db.repositories._pg.vector_search import *  # noqa: F401,F403
