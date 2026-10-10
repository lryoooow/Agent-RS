from __future__ import annotations

import hashlib
import logging
import traceback
from pathlib import Path
from typing import Any


def log_exception_diagnostics(
    logger: logging.Logger,
    event: str,
    exc: BaseException,
    **fields: Any,
) -> str:
    """Log actionable exception structure without persisting its raw message.

    Provider SDK and tool exceptions can include API keys, signed URLs or user
    content in ``str(exc)``.  We retain the exception type, source frames,
    status, caller fields and a stable fingerprint while deliberately omitting
    the raw message.
    """

    frames = traceback.extract_tb(exc.__traceback__)
    trace = " > ".join(
        f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames[-6:]
    ) or "<no-traceback>"
    exception_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    status = getattr(exc, "status_code", None)
    fingerprint_source = f"{event}|{exception_type}|{status}|{trace}"
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:16]
    extra = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    logger.warning(
        "%s exception_type=%s status=%s fingerprint=%s trace=%s%s",
        event,
        exception_type,
        status if status is not None else "unknown",
        fingerprint,
        trace,
        f" {extra}" if extra else "",
    )
    return fingerprint
