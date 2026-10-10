#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
npm --prefix Agent-frontend ci
npm --prefix Agent-frontend run build
./ops/build_satvis.sh
python ./ops/verify_release.py "$repo_root"
