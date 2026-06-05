from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.paths import imagery_root
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

IMAGERY_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def read_imagery_metadata(imagery_id: str) -> dict[str, Any] | None:
    if not IMAGERY_ID_PATTERN.fullmatch(imagery_id):
        return None
    return read_metadata_file(imagery_root() / imagery_id / "metadata.json")


def read_metadata_file(meta_file: Path) -> dict[str, Any] | None:
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Invalid imagery metadata skipped: %s", meta_file, exc_info=True)
        return None


def imagery_owner_id(meta: dict[str, Any]) -> str:
    return str(meta.get("owner_user_id") or get_settings().default_user_id)


def user_owns_imagery(imagery_id: str, user_id: str | None) -> bool:
    if not user_id:
        return False
    meta = read_imagery_metadata(imagery_id)
    if meta is None:
        return False
    return imagery_owner_id(meta) == user_id


def known_imagery_ids_for_user(user_id: str | None) -> set[str]:
    if not user_id:
        return set()
    root = imagery_root()
    if not root.exists():
        return set()
    result: set[str] = set()
    for entry in root.iterdir():
        if not entry.is_dir() or not IMAGERY_ID_PATTERN.fullmatch(entry.name):
            continue
        meta = read_metadata_file(entry / "metadata.json")
        if meta is None:
            continue
        if imagery_owner_id(meta) == user_id:
            result.add(entry.name)
    return result


def iter_user_imagery_metadata(user_id: str | None) -> list[tuple[str, dict[str, Any]]]:
    if not user_id:
        return []
    root = imagery_root()
    if not root.exists():
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not IMAGERY_ID_PATTERN.fullmatch(entry.name):
            continue
        meta = read_metadata_file(entry / "metadata.json")
        if meta is None:
            continue
        if imagery_owner_id(meta) == user_id:
            items.append((entry.name, meta))
    return items
