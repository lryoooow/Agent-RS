from __future__ import annotations
import asyncio
import copy
import gzip
import importlib.util
import json
import sys
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import satellite_catalog as sc


def row(identifier=39084, name="LANDSAT 8"):
    return {"NORAD_CAT_ID": identifier, "OBJECT_NAME": name, "EPOCH": "2026-10-10T02:00:00",
            "MEAN_MOTION": 14.5, "ECCENTRICITY": 0.001, "INCLINATION": 98.2,
            "RA_OF_ASC_NODE": 60.0, "ARG_OF_PERICENTER": 10.0, "MEAN_ANOMALY": 90.0}


def catalog(tmp_path, age=0):
    value = sc.SatelliteCatalog(tmp_path / "catalog.zip")
    updated = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    value.index = {"updated": updated, "groups": [{"name": name, "count": 1, "updated": updated} for name in sc.GROUPS]}
    value.payloads = {name: gzip.compress(json.dumps([row()]).encode()) for name in sc.GROUPS}
    return value


def test_actual_bundled_catalog_has_usable_satellites():
    index, payloads = sc.read_snapshot(sc.SEED)
    assert len(index["groups"]) == 15
    resource = sc.validate_records(sc.inflate(payloads["resource"]))
    names = {item["OBJECT_NAME"] for item in resource}
    assert {"LANDSAT 8", "LANDSAT 9", "SENTINEL-2A", "SENTINEL-2B", "SENTINEL-2C"} <= names
    landsat = next(item for item in resource if item["NORAD_CAT_ID"] == 39084)
    assert landsat["metadata"]["swathPortKm"] == 92.5
    assert next(item["count"] for item in index["groups"] if item["name"] == "active") > 1000


@pytest.mark.parametrize("value", [[], {}, "<html>upstream error</html>", [row(), row()],
    [{**row(), "NORAD_CAT_ID": True}], [{**row(), "MEAN_MOTION": 0}],
    [{**row(), "ECCENTRICITY": 1.2}], [{**row(), "INCLINATION": float("nan")}],
    [{**row(), "EPOCH": "bad-date"}], [{**row(), "OBJECT_NAME": ""}],
    [{**row(), "RA_OF_ASC_NODE": None}]])
def test_invalid_upstream_cannot_replace_good_data(value):
    raw = value.encode() if isinstance(value, str) else json.dumps(value).encode()
    with pytest.raises((ValueError, KeyError, TypeError)):
        sc.validate_records(raw)


def test_size_and_decompression_limits(monkeypatch):
    monkeypatch.setattr(sc, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        sc.validate_records(b"x" * 11)
    with pytest.raises(ValueError, match="decompression"):
        sc.inflate(gzip.compress(b"x" * 11))


async def test_concurrent_stale_requests_schedule_one_refresh(tmp_path):
    value = catalog(tmp_path, sc.REFRESH_SECONDS + 1)
    event = asyncio.Event()
    starts = []
    async def refresh():
        starts.append(1)
        await event.wait()
    value.refresh = refresh
    await asyncio.gather(*(value.ready() for _ in range(50)))
    await asyncio.sleep(0)
    assert starts == [1]
    assert value.status()["refreshing"] is True
    event.set()
    await value.refresh_task
    await value.ready()
    assert starts == [1]  # even failed refreshes cannot trigger per-user upstream storms


async def test_refresh_retains_good_groups_on_html_timeout_and_empty(tmp_path):
    value = catalog(tmp_path)
    original = copy.deepcopy(value.payloads)
    calls = []
    async def fetch(client, source):
        calls.append(source)
        if source == "active": raise httpx.ReadTimeout("offline")
        if source == "resource": return sc.validate_records(b"<html>bad gateway</html>")
        if source == "weather": return sc.validate_records(b"[]")
        return [row()]
    value._fetch = fetch
    await value.refresh()
    assert sorted(calls) == sc.SOURCES and len(calls) == len(set(calls)) == 8
    assert value.payloads["resource"] == original["resource"]
    assert value.payloads["active"] == original["active"]
    assert value.payloads["weather"] == original["weather"]
    assert value.status()["stale"] is True
    assert next(item for item in value.index["groups"] if item["name"] == "resource")["lastError"]
    index, payloads, source = sc._load(value.cache)
    assert payloads["resource"] == original["resource"] and source == "cache"


async def test_successful_refresh_keeps_curated_metadata_and_group_filters(tmp_path):
    value = catalog(tmp_path)
    value.payloads["resource"] = gzip.compress(json.dumps([{**row(), "metadata": {"owner": "US"}}]).encode())
    records = [row()] + [row(i + 90000, name) for i, name in enumerate(["STARLINK-1", "ONEWEB-1", "GLOBALSTAR-1", "IRIDIUM-1", "FLOCK-1", "LEMUR-1", "EUTELSAT-1"])]
    async def fetch(client, source): return records
    value._fetch = fetch
    await value.refresh()
    assert value.source == "network" and not value.status()["stale"]
    landsat = sc.validate_records(sc.inflate(value.payloads["resource"]))[0]
    assert landsat["metadata"]["owner"] == "US" and landsat["metadata"]["swathPortKm"] == 92.5
    assert [item["OBJECT_NAME"] for item in json.loads(sc.inflate(value.payloads["oneweb"]))] == ["ONEWEB-1"]
    reloaded = sc._load(value.cache)
    assert reloaded[0] == value.index and reloaded[1] == value.payloads


async def test_fetch_rejects_http_failure_html_and_oversize(monkeypatch, tmp_path):
    value = catalog(tmp_path)
    for response in [httpx.Response(503), httpx.Response(200, text="<html>error</html>"), httpx.Response(200, content=b"x" * 11)]:
        monkeypatch.setattr(sc, "MAX_BYTES", 10)
        def handle(request):
            assert request.url.host == "celestrak.org"
            assert request.url.params["GROUP"] == "weather"
            return response
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises((ValueError, httpx.HTTPError)):
                await value._fetch(client, "weather")


def test_corrupt_disk_cache_uses_bundled_catalog(tmp_path):
    path = tmp_path / "catalog.zip"
    path.write_bytes(b"not a zip")
    index, payloads, source = sc._load(path)
    assert source == "bundled" and len(payloads) == 15


async def test_shutdown_cancels_only_refresh_and_resets_global(monkeypatch, tmp_path):
    value = catalog(tmp_path)
    value.refresh_task = asyncio.create_task(asyncio.sleep(100))
    monkeypatch.setattr(sc, "_catalog", value)
    await sc.close_catalog()
    assert value.refresh_task.cancelled() and sc._catalog is None


def test_api_matches_satvis_paths_and_has_no_unrestricted_proxy(monkeypatch, tmp_path):
    from app.api.routes import satellites
    from app.main import create_app
    from app.core.settings import get_settings
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    get_settings.cache_clear()
    value = catalog(tmp_path)
    monkeypatch.setattr(satellites, "get_catalog", lambda: value)
    client = TestClient(create_app())
    response = client.get("/api/groups.json")
    assert response.status_code == 200 and len(response.json()["groups"]) == 15
    response = client.get("/api/gp/resource.json")
    assert response.status_code == 200 and response.json()[0]["OBJECT_NAME"] == "LANDSAT 8"
    assert response.headers["content-encoding"] == "gzip"
    assert client.get("/api/gp/not-a-valid-group.json").status_code == 404
    get_settings.cache_clear()


def test_api_requires_login_when_auth_enabled(monkeypatch):
    import app.main as main
    from app.core.settings import get_settings
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    async def no_user(token): return None
    monkeypatch.setattr(main, "get_session_user", no_user)
    get_settings.cache_clear()
    client = TestClient(main.create_app())
    assert client.get("/api/groups.json").status_code == 401
    assert client.get("/api/gp/resource.json").status_code == 401
    get_settings.cache_clear()


def verifier():
    path = Path(__file__).resolve().parents[3] / "ops/verify_release.py"
    spec = importlib.util.spec_from_file_location("catalog_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_fixture(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"groups": [{"name": "resource"}]}))
    (tmp_path / "index.json").write_text(json.dumps({"groups": [{"name": "resource", "count": 1}]}))
    (tmp_path / "resource.json").write_text(json.dumps([row()]))
    return tmp_path / "config.json"


@pytest.mark.parametrize("broken", ["missing", "empty", "html", "count", "wrong-group", "no-orbit"])
def test_release_gate_rejects_unusable_catalogue(tmp_path, broken):
    config = release_fixture(tmp_path)
    if broken == "missing": (tmp_path / "resource.json").unlink()
    if broken == "empty": (tmp_path / "resource.json").write_text("[]")
    if broken == "html": (tmp_path / "resource.json").write_text("<html>error</html>")
    if broken == "count": (tmp_path / "index.json").write_text(json.dumps({"groups": [{"name": "resource", "count": 20}]}))
    if broken == "wrong-group": (tmp_path / "index.json").write_text(json.dumps({"groups": [{"name": "../private", "count": 1}]}))
    if broken == "no-orbit": (tmp_path / "resource.json").write_text(json.dumps([{"NORAD_CAT_ID": 39084, "OBJECT_NAME": "LANDSAT 8", "EPOCH": "2026-10-10"}]))
    with pytest.raises((ValueError, OSError)):
        verifier().verify_catalog(tmp_path, config)


def test_release_gate_accepts_valid_data(tmp_path):
    config = release_fixture(tmp_path)
    assert verifier().verify_catalog(tmp_path, config) == 1


async def test_all_upstreams_offline_still_serves_the_complete_catalogue(tmp_path):
    value = catalog(tmp_path, sc.REFRESH_SECONDS + 1)
    original = copy.deepcopy(value.payloads)
    async def fetch(client, source): raise httpx.ConnectError("offline")
    value._fetch = fetch
    await value.refresh()
    assert value.payloads == original
    assert len(value.index["groups"]) == 15
    assert all(group.get("lastError") for group in value.index["groups"])
    assert value.status()["stale"]


async def test_cache_write_failure_cannot_publish_partial_results(monkeypatch, tmp_path):
    value = catalog(tmp_path)
    original = copy.deepcopy(value.payloads)
    async def fetch(client, source): return [row()]
    def fail(*args): raise OSError("disk unavailable")
    value._fetch = fetch
    monkeypatch.setattr(sc, "_persist", fail)
    await value.refresh()
    assert value.payloads == original
    assert all(group["count"] == 1 for group in value.index["groups"])
