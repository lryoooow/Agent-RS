#!/usr/bin/env bash
set -euo pipefail

# Reproducible satvis vendor build. The output is copied after the Agent-RS
# frontend build so Vite cannot delete it. Run from the Agent-RS repository root.
SATVIS_REPOSITORY="https://github.com/Flowm/satvis.git"
SATVIS_REVISION="8e36f03"
SATVIS_WORKDIR="${SATVIS_WORKDIR:-/home/LRY/.cache/agent-rs-satvis}"
TARGET_DIR="${SATVIS_TARGET_DIR:-$(pwd)/Agent-frontend/dist/satvis}"
PATCH_FILE="$(pwd)/ops/satvis-agent-rs.patch"

if [ ! -d "$SATVIS_WORKDIR/.git" ]; then
  git clone "$SATVIS_REPOSITORY" "$SATVIS_WORKDIR"
fi
git -C "$SATVIS_WORKDIR" fetch --depth 1 origin "$SATVIS_REVISION"
git -C "$SATVIS_WORKDIR" reset --hard
git -C "$SATVIS_WORKDIR" checkout --detach FETCH_HEAD
git -C "$SATVIS_WORKDIR" reset --hard FETCH_HEAD
git -C "$SATVIS_WORKDIR" apply "$PATCH_FILE"
cd "$SATVIS_WORKDIR"
corepack pnpm install --frozen-lockfile
corepack pnpm update-gp
corepack pnpm build

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -a dist/. "$TARGET_DIR/"
cp LICENSE "$TARGET_DIR/LICENSE.txt"
