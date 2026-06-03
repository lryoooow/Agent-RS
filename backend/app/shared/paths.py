from __future__ import annotations

from pathlib import Path

from app.shared.settings import get_settings


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return project_root() / path


def imagery_root(*, create: bool = False) -> Path:
    root = resolve_project_path(get_settings().imagery_upload_dir)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root
