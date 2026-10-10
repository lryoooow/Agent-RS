from __future__ import annotations

from pathlib import Path

from app.documents.task_registry import cleanup_stale_job_uploads


class _Settings:
    def __init__(self, upload_dir: Path) -> None:
        self.storage_upload_dir = str(upload_dir)


def test_cleanup_stale_job_uploads_stays_inside_configured_root(tmp_path, monkeypatch) -> None:
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    stale = upload_root / "stale.bin"
    stale.write_bytes(b"stale")
    outside = tmp_path / "keep.bin"
    outside.write_bytes(b"keep")
    monkeypatch.setattr(
        "app.documents.task_registry.get_settings",
        lambda: _Settings(upload_root),
    )

    removed = cleanup_stale_job_uploads([str(stale), str(outside)])

    assert removed == 1
    assert not stale.exists()
    assert outside.read_bytes() == b"keep"
