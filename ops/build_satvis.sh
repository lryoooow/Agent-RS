#!/usr/bin/env bash
set -euo pipefail

# Reproducible satvis vendor build. The output is copied after the Agent-RS
# frontend build so Vite cannot delete it. Run from the Agent-RS repository root.
SATVIS_REPOSITORY="https://github.com/Flowm/satvis.git"
SATVIS_REVISION="8e36f03"
SATVIS_WORKDIR="${SATVIS_WORKDIR:-/home/LRY/.cache/agent-rs-satvis}"
TARGET_DIR="${SATVIS_TARGET_DIR:-$(pwd)/Agent-frontend/dist/satvis}"
REPO_ROOT="$(pwd)"
PATCH_FILE="$REPO_ROOT/ops/satvis-agent-rs.patch"

if [ ! -d "$SATVIS_WORKDIR/.git" ]; then
  git clone "$SATVIS_REPOSITORY" "$SATVIS_WORKDIR"
fi
if git -C "$SATVIS_WORKDIR" fetch --depth 1 origin "$SATVIS_REVISION"; then
  SATVIS_CHECKOUT="FETCH_HEAD"
elif git -C "$SATVIS_WORKDIR" cat-file -e "${SATVIS_REVISION}^{commit}"; then
  echo "SatVis upstream unavailable; using verified cached revision ${SATVIS_REVISION}." >&2
  SATVIS_CHECKOUT="$SATVIS_REVISION"
else
  echo "SatVis revision ${SATVIS_REVISION} is unavailable locally and fetch failed." >&2
  exit 1
fi
git -C "$SATVIS_WORKDIR" reset --hard
git -C "$SATVIS_WORKDIR" checkout --detach "$SATVIS_CHECKOUT"
git -C "$SATVIS_WORKDIR" reset --hard "$SATVIS_CHECKOUT"
git -C "$SATVIS_WORKDIR" apply "$PATCH_FILE"
cd "$SATVIS_WORKDIR"
if command -v corepack >/dev/null 2>&1; then
  PNPM=(corepack pnpm)
else
  PNPM=(npx --yes pnpm@11.9.0)
fi
"${PNPM[@]}" install --frozen-lockfile
if ! "${PNPM[@]}" update-gp; then
  echo "Satellite catalog refresh failed; building with the pinned bundled catalog." >&2
fi
python3 "$REPO_ROOT/ops/prepare_satellite_catalog.py" data/gp
"${PNPM[@]}" build

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -a dist/. "$TARGET_DIR/"
cp LICENSE "$TARGET_DIR/LICENSE.txt"

python3 "$REPO_ROOT/ops/verify_release.py" "$REPO_ROOT"
