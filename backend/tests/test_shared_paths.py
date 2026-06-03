from pathlib import Path

from app.core.paths import imagery_root, project_root
from app.core.settings import get_settings


def test_imagery_root_resolves_relative_to_project(monkeypatch) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", "storage/imagery")
    get_settings.cache_clear()

    assert imagery_root() == project_root() / "storage" / "imagery"


def test_imagery_root_keeps_absolute_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    get_settings.cache_clear()

    assert imagery_root() == tmp_path / "imagery"
