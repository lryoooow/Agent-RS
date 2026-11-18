"""Per-invocation progress sink inherited by the operator transport."""
from contextlib import contextmanager
from contextvars import ContextVar

from app.mcp.types import ProgressCallback

_sink: ContextVar[ProgressCallback | None] = ContextVar("operator_mcp_progress", default=None)


def current_progress():
    return _sink.get()


@contextmanager
def progress_scope(callback):
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)
