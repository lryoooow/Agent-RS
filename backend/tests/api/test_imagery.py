from io import BytesIO
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.main import create_app
from app.core.settings import get_settings


def make_client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("IMAGERY_WORKING_MAX_DIMENSION", "4")
    monkeypatch.setenv("IMAGERY_PREVIEW_MAX_DIMENSION", "3")
    get_settings.cache_clear()
    return TestClient(create_app())


def make_geotiff(*, width: int = 6, height: int = 4, count: int = 4) -> bytes:
    buffer = BytesIO()
    data = np.zeros((count, height, width), dtype=np.uint16)
    for band in range(count):
        data[band] = np.arange(width * height, dtype=np.uint16).reshape(height, width) + band
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(100, 20, 0.01, 0.01),
    ) as dst:
        dst.write(data)
    return buffer.getvalue()


def test_imagery_upload_generates_working_raster_and_preview(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )

    assert response.status_code == 200
    body = response.json()
    imagery_dir = tmp_path / "imagery" / body["imagery_id"]
    assert body["preview_url"] == f"/api/imagery/{body['imagery_id']}/results/preview.png"
    assert body["working_width"] == 4
    assert body["working_height"] == 3
    assert body["compressed"] is True
    assert body["sha256"]
    assert body["source_size_bytes"] > 0
    assert body["working_size_bytes"] > 0
    assert (imagery_dir / "source.tif").exists()
    assert (imagery_dir / "working.tif").exists()
    assert (imagery_dir / "results" / "preview.png").exists()
    with rasterio.open(imagery_dir / "working.tif") as src:
        assert src.width == 4
        assert src.height == 3
        assert src.count == 4
        assert src.compression.value.lower() == "deflate"


def test_imagery_upload_rejects_invalid_geotiff_without_500(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("broken.tif", b"not a geotiff", "image/tiff")},
    )

    assert response.status_code == 422
    assert "GeoTIFF" in response.json()["detail"]
    assert "not a geotiff" not in response.json()["detail"]


def test_imagery_upload_rejects_oversized_file_after_closing_handle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("IMAGERY_MAX_FILE_BYTES", "8")
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("large.tif", b"0123456789", "image/tiff")},
    )

    assert response.status_code == 413
    imagery_root = tmp_path / "imagery"
    assert not imagery_root.exists() or list(imagery_root.iterdir()) == []


def test_imagery_result_rejects_invalid_id(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)

    response = client.get("/api/imagery/..invalid/results/preview.png")

    assert response.status_code == 400


def test_imagery_result_serves_preview_from_safe_path(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    imagery_id = upload.json()["imagery_id"]

    response = client.get(f"/api/imagery/{imagery_id}/results/preview.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")


def test_imagery_list_hides_other_user_metadata(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    other_dir = tmp_path / "imagery" / "94e758f38ede"
    other_dir.mkdir(parents=True)
    (other_dir / "metadata.json").write_text(
        json.dumps({"filename": "other.tif", "owner_user_id": "other-user"}),
        encoding="utf-8",
    )

    response = client.get("/api/imagery")

    assert response.status_code == 200
    assert response.json() == []


def test_imagery_detail_and_result_reject_other_owner(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    other_dir = tmp_path / "imagery" / "94e758f38ede"
    results_dir = other_dir / "results"
    results_dir.mkdir(parents=True)
    (other_dir / "metadata.json").write_text(
        json.dumps({"filename": "other.tif", "owner_user_id": "other-user"}),
        encoding="utf-8",
    )
    (results_dir / "preview.png").write_bytes(b"png")

    detail = client.get("/api/imagery/94e758f38ede")
    result = client.get("/api/imagery/94e758f38ede/results/preview.png")
    delete = client.delete("/api/imagery/94e758f38ede")

    assert detail.status_code == 404
    assert result.status_code == 404
    assert delete.status_code == 404
    assert other_dir.exists()


def test_imagery_list_skips_broken_metadata(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    broken_dir = tmp_path / "imagery" / "94e758f38ede"
    broken_dir.mkdir(parents=True)
    (broken_dir / "metadata.json").write_text("{bad json", encoding="utf-8")

    response = client.get("/api/imagery")

    assert response.status_code == 200
    assert response.json() == []


def test_imagery_delete_removes_directory(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    imagery_id = upload.json()["imagery_id"]
    imagery_dir = tmp_path / "imagery" / imagery_id

    response = client.delete(f"/api/imagery/{imagery_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert not imagery_dir.exists()


def test_imagery_cleanup_removes_old_orphan_directory(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    orphan_dir = tmp_path / "imagery" / "94e758f38ede"
    orphan_dir.mkdir(parents=True)
    old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
    orphan_dir.touch()
    import os

    os.utime(orphan_dir, (old_timestamp, old_timestamp))

    response = client.post("/api/imagery/cleanup")

    assert response.status_code == 200
    assert response.json()["removed"] == ["94e758f38ede"]
    assert not orphan_dir.exists()
