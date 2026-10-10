"""Bounded, same-origin SatVis catalogue with a shipped last-known-good seed."""
from __future__ import annotations

import asyncio
import gzip
import io
import json
import logging
import math
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.paths import imagery_root

log = logging.getLogger(__name__)
SEED = Path(__file__).resolve().parents[1] / "data" / "satellite_catalog"
CONFIG = json.loads((SEED / "config.json").read_text(encoding="utf-8"))
GROUPS = {item["name"]: item for item in CONFIG["groups"]}
SOURCES = sorted({source["celestrak"] for item in GROUPS.values() for source in item["sources"]})
REFRESH_SECONDS = 6 * 60 * 60
MAX_BYTES = 12 * 1024 * 1024
MAX_RECORDS = 25_000
ORBIT_FIELDS = ("MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY")


def validate_records(raw: bytes) -> list[dict]:
    if len(raw) > MAX_BYTES:
        raise ValueError("satellite response exceeds size limit")
    records = json.loads(raw)
    if not isinstance(records, list) or not 0 < len(records) <= MAX_RECORDS:
        raise ValueError("satellite response must contain a non-empty bounded OMM array")
    ids = set()
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("OBJECT_NAME"), str) or not row["OBJECT_NAME"].strip():
            raise ValueError("satellite record has no name")
        identifier = row.get("NORAD_CAT_ID")
        if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0 or identifier in ids:
            raise ValueError("satellite record has an invalid or duplicate NORAD ID")
        ids.add(identifier)
        epoch = datetime.fromisoformat(row["EPOCH"].replace("Z", "+00:00"))
        if epoch.year < 1957:
            raise ValueError("invalid orbital epoch")
        if any(isinstance(row.get(key), bool) or not isinstance(row.get(key), (int, float)) or not math.isfinite(row[key]) for key in ORBIT_FIELDS):
            raise ValueError("invalid orbital elements")
        if row["MEAN_MOTION"] <= 0 or not 0 <= row["ECCENTRICITY"] < 1 or not 0 <= row["INCLINATION"] <= 180:
            raise ValueError("orbital elements outside valid range")
    return records


def inflate(payload: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("satellite decompression exceeds size limit")
    return raw


def read_snapshot(directory: Path) -> tuple[dict, dict[str, bytes]]:
    index = json.loads(inflate((directory / "index.json.gz").read_bytes()))
    payloads = {name: (directory / (name + ".json.gz")).read_bytes() for name in GROUPS}
    verify_snapshot(index, payloads)
    return index, payloads


def verify_snapshot(index: dict, payloads: dict[str, bytes]) -> None:
    groups = index.get("groups")
    if not isinstance(groups, list) or len(groups) != len(GROUPS) or {g.get("name") for g in groups} != set(GROUPS):
        raise ValueError("satellite index does not contain the expected groups")
    datetime.fromisoformat(index["updated"].replace("Z", "+00:00"))
    for group in groups:
        raw = inflate(payloads[group["name"]])
        records = validate_records(raw)
        if group["count"] != len(records):
            raise ValueError("satellite index count differs from payload")
        datetime.fromisoformat(group["updated"].replace("Z", "+00:00"))


def _load(cache: Path) -> tuple[dict, dict[str, bytes], str]:
    if cache.is_file():
        try:
            if cache.stat().st_size > 2 * MAX_BYTES:
                raise ValueError("satellite cache exceeds size limit")
            with zipfile.ZipFile(cache) as archive:
                if any(info.file_size > MAX_BYTES for info in archive.infolist()):
                    raise ValueError("satellite cache member exceeds size limit")
                index = json.loads(archive.read("index.json"))
                payloads = {name: archive.read(name + ".json.gz") for name in GROUPS}
            verify_snapshot(index, payloads)
            return index, payloads, "cache"
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, EOFError, AttributeError):
            log.warning("Invalid satellite cache; using the bundled catalogue")
    index, payloads = read_snapshot(SEED)
    return index, payloads, "bundled"


def _encode_groups(data: dict[str, list[dict]], old: dict[str, bytes]) -> dict[str, bytes]:
    metadata = {}
    for payload in old.values():
        for row in json.loads(inflate(payload)):
            if row.get("metadata"):
                metadata[row["NORAD_CAT_ID"]] = row["metadata"]
    for fact in CONFIG["satellites"]:
        identifier = fact["noradId"]
        metadata[identifier] = {**metadata.get(identifier, {}), **fact.get("metadata", {})}
    encoded = {}
    for name, rows in data.items():
        enriched = [{**row, "metadata": {**metadata.get(row["NORAD_CAT_ID"], {}), **row.get("metadata", {})}} for row in rows]
        encoded[name] = gzip.compress(json.dumps(enriched, separators=(",", ":"), allow_nan=False).encode(), mtime=0)
    return encoded


def _persist(cache: Path, index: dict, payloads: dict[str, bytes]) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".pending")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("index.json", json.dumps(index))
            for name, payload in payloads.items():
                archive.writestr(name + ".json.gz", payload)
        temporary.replace(cache)
    finally:
        temporary.unlink(missing_ok=True)


class SatelliteCatalog:
    def __init__(self, cache: Path):
        self.cache = cache
        self.index: dict = {}
        self.payloads: dict[str, bytes] = {}
        self.source = "bundled"
        self.lock = asyncio.Lock()
        self.refresh_task: asyncio.Task | None = None
        self.next_refresh = 0.0

    async def ready(self) -> None:
        if not self.index:
            async with self.lock:
                if not self.index:
                    self.index, self.payloads, self.source = await asyncio.to_thread(_load, self.cache)
        newest = max(datetime.fromisoformat(g["updated"].replace("Z", "+00:00")).timestamp() for g in self.index["groups"])
        if time.time() - newest >= REFRESH_SECONDS and time.monotonic() >= self.next_refresh and (self.refresh_task is None or self.refresh_task.done()):
            self.next_refresh = time.monotonic() + REFRESH_SECONDS
            self.refresh_task = asyncio.create_task(self.refresh(), name="satellite-catalog-refresh")

    async def _fetch(self, client: httpx.AsyncClient, source: str) -> list[dict]:
        # Fixed upstream and sources only: never a user-supplied URL or GROUP.
        async with asyncio.timeout(20):
            async with client.stream("GET", "https://celestrak.org/NORAD/elements/gp.php", params={"GROUP": source, "FORMAT": "JSON"}) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("satellite response exceeds size limit")
                    chunks.append(chunk)
        return await asyncio.to_thread(validate_records, b"".join(chunks))

    async def refresh(self) -> None:
        # One refresh per process, eight deduplicated sources per six hours.
        try:
            fetched, failures = {}, {}
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), follow_redirects=False, headers={"User-Agent": "Agent-RS/SatVis-catalog"}) as client:
                for source in SOURCES:
                    try:
                        fetched[source] = await self._fetch(client, source)
                    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                        failures[source] = type(exc).__name__
                        log.warning("Satellite upstream %s unavailable (%s); keeping valid cache", source, type(exc).__name__)
            now = datetime.now(timezone.utc).isoformat()
            updated_rows, statuses = {}, []
            for previous in self.index["groups"]:
                name = previous["name"]
                definition = GROUPS[name]
                sources = [item["celestrak"] for item in definition["sources"]]
                reason = next((failures[item] for item in sources if item in failures), None)
                if not reason:
                    pool = {row["NORAD_CAT_ID"]: row for source in sources for row in fetched[source]}
                    pattern = definition.get("select", {}).get("namePattern")
                    selected = {identifier: row for identifier, row in pool.items() if not pattern or re.search(pattern, row["OBJECT_NAME"])}
                    for satellite in definition.get("satellites", []):
                        identifier = satellite["noradId"]
                        if identifier in pool:
                            selected[identifier] = pool[identifier]
                    if selected:
                        rows = list(selected.values())
                        updated_rows[name] = rows
                        statuses.append({"name": name, "count": len(rows), "updated": now})
                        continue
                    reason = "EmptyGroup"
                statuses.append({**previous, "lastError": reason, "lastErrorAt": now})
            encoded = await asyncio.to_thread(_encode_groups, updated_rows, self.payloads)
            payloads = {**self.payloads, **encoded}
            index = {"updated": now if updated_rows else self.index["updated"], "groups": statuses}
            await asyncio.to_thread(_persist, self.cache, index, payloads)
            # Publish index and payloads together without an intervening await.
            self.index, self.payloads = index, payloads
            self.source = "network" if len(updated_rows) == len(GROUPS) else "cache"
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Satellite refresh failed; current catalogue remains available")

    def status(self) -> dict:
        now = time.time()
        groups = [{**group, "stale": now - datetime.fromisoformat(group["updated"].replace("Z", "+00:00")).timestamp() >= REFRESH_SECONDS} for group in self.index["groups"]]
        return {**self.index, "groups": groups, "source": self.source, "stale": any(group["stale"] or group.get("lastError") for group in groups), "refreshing": self.refresh_task is not None and not self.refresh_task.done()}


_catalog: SatelliteCatalog | None = None


def get_catalog() -> SatelliteCatalog:
    global _catalog
    if _catalog is None:
        _catalog = SatelliteCatalog(imagery_root().parent / "satellite_catalog" / "catalog.zip")
    return _catalog


async def close_catalog() -> None:
    global _catalog
    if _catalog and _catalog.refresh_task and not _catalog.refresh_task.done():
        _catalog.refresh_task.cancel()
        await asyncio.gather(_catalog.refresh_task, return_exceptions=True)
    _catalog = None
