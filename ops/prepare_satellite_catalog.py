#!/usr/bin/env python3
"""Ship a usable SatVis offline catalogue after every frontend build."""
from __future__ import annotations
import gzip
import hashlib
import shutil
import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    seed = root / "backend/app/data/satellite_catalog"
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "Agent-frontend/dist/satvis/data/gp"
    target.mkdir(parents=True, exist_ok=True)
    assets = root / "ops/satvis-assets"
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    sky = target.parent / "starmap"
    sky.mkdir(parents=True, exist_ok=True)
    for item in manifest["assets"]:
        name = item["name"]
        if Path(name).name != name or not name.endswith(".webp"):
            raise ValueError("invalid sky texture filename")
        source = assets / "starmap" / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("sky texture checksum mismatch")
        shutil.copyfile(source, sky / name)
    index = json.loads(gzip.decompress((seed / "index.json.gz").read_bytes()))
    # Keep a complete, newer upstream refresh; replace partial/empty output.
    try:
        from verify_release import verify_catalog
        verify_catalog(target, seed / "config.json")
        existing = json.loads((target / "index.json").read_text(encoding="utf-8"))
        from datetime import datetime
        if datetime.fromisoformat(existing["updated"].replace("Z", "+00:00")) >= datetime.fromisoformat(index["updated"].replace("Z", "+00:00")):
            print("SatVis fallback retained: validated newer upstream catalogue")
            return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    for entry in [{"name": "index"}, *index["groups"]]:
        name = entry["name"]
        if not name.replace("-", "").isalnum():
            raise ValueError("invalid satellite group filename")
        (target / (name + ".json")).write_bytes(gzip.decompress((seed / (name + ".json.gz")).read_bytes()))
    print(f"SatVis fallback prepared: {len(index['groups'])} groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
