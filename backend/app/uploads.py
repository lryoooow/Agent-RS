from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

_UPLOAD_CHUNK_BYTES = 1024 * 1024
logger = logging.getLogger(__name__)


class UploadSizeExceeded(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"Upload exceeds {max_bytes} bytes")
        self.max_bytes = max_bytes


@dataclass(frozen=True, slots=True)
class StreamedUpload:
    path: Path
    size: int


async def stream_upload_to_temp(
    file: UploadFile,
    *,
    max_bytes: int,
    suffix: str,
    directory: Path | None = None,
    chunk_bytes: int = _UPLOAD_CHUNK_BYTES,
) -> StreamedUpload:
    """Stream an UploadFile to disk with a hard byte limit and cancellation cleanup."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    temp_file = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix,
        dir=str(directory) if directory is not None else None,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()
    completed = False
    total_bytes = 0
    try:
        with temp_path.open("wb") as target:
            while True:
                chunk = await file.read(chunk_bytes)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise UploadSizeExceeded(max_bytes)
                target.write(chunk)
        completed = True
        return StreamedUpload(path=temp_path, size=total_bytes)
    finally:
        if not completed:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to remove partial upload: %s", temp_path, exc_info=True)
        try:
            await file.close()
        except Exception:
            # The request lifecycle will make a second best-effort close. The
            # on-disk file has already been removed on every failure path.
            pass
