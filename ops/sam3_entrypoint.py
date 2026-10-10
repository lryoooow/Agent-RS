"""Deployment bridge for the existing SAM3 unit; model assets stay in SAM3_LAB_ROOT."""
import os
import sys
from pathlib import Path

release = Path(os.environ.get("AGENT_RS_ROOT", "/home/LRY/Agent-RS-current")).resolve()
sys.path.insert(0, str(release))
from ops.sam3_service import app  # noqa: E402,F401
