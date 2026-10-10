#!/usr/bin/env python3
"""Fail a release before cutover when required frontend payloads are missing."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path


def verify_catalog(directory: Path, config_path: Path) -> int:
    expected = {group["name"] for group in json.loads(config_path.read_text(encoding="utf-8"))["groups"]}
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    groups = index["groups"]
    if len(groups) != len(expected) or {group["name"] for group in groups} != expected:
        raise ValueError("satellite catalogue is missing expected groups")
    for group in groups:
        name = group["name"]
        # Only known core group names can become paths; malformed release data
        # cannot validate an arbitrary file outside the catalogue directory.
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise ValueError("invalid satellite group name")
        path = directory / (name + ".json")
        if path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("satellite group is too large")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows or len(rows) != group["count"]:
            raise ValueError(f"satellite group {name} is empty or has an incorrect count")
        for row in rows:
            if not isinstance(row.get("NORAD_CAT_ID"), int) or row["NORAD_CAT_ID"] <= 0 or not row.get("OBJECT_NAME") or not row.get("EPOCH"):
                raise ValueError(f"satellite group {name} contains invalid OMM records")
            for key in ("MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY"):
                value = row.get(key)
                if not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise ValueError(f"satellite group {name} contains invalid orbital elements")
    return len(groups)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    dist = root / "Agent-frontend" / "dist"
    required = [
        dist / "index.html",
        dist / "satvis" / "index.html",
        dist / "satvis" / "sw.js",
        dist / "satvis" / "LICENSE.txt",
        dist / "satvis/data/starmap/deepstar_2020_1024_px.webp",
        dist / "satvis/data/starmap/deepstar_2020_2048_px.webp",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file() or path.stat().st_size == 0]
    if missing:
        print("release verification failed; missing: " + ", ".join(missing), file=sys.stderr)
        return 1

    satvis_html = required[1].read_text(encoding="utf-8")
    entries = re.findall(r'(?:src|href)="\.(/assets/[^"]+)"', satvis_html)
    missing_entries = [entry for entry in entries if not (dist / "satvis" / entry.lstrip("/")).is_file()]
    if not entries or missing_entries:
        print(
            "release verification failed; SatVis entry assets missing: "
            + (", ".join(missing_entries) if missing_entries else "no entry assets found"),
            file=sys.stderr,
        )
        return 1

    try:
        sky_manifest = json.loads((root / "ops/satvis-assets/manifest.json").read_text(encoding="utf-8"))
        for item in sky_manifest["assets"]:
            name = item["name"]
            if Path(name).name != name:
                raise ValueError("invalid sky texture filename")
            if hashlib.sha256((dist / "satvis/data/starmap" / name).read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("sky texture checksum mismatch")
        group_count = verify_catalog(dist / "satvis/data/gp", root / "backend/app/data/satellite_catalog/config.json")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"release verification failed; satellite catalogue unavailable: {exc}", file=sys.stderr)
        return 1

    print(f"release verified: {root} (SatVis assets: {len(entries)}, satellite groups: {group_count})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
