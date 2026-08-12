#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

backend_pid=""
frontend_pid=""

cleanup() {
  trap - EXIT INT TERM HUP
  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
  [[ -z "$frontend_pid" ]] || wait "$frontend_pid" 2>/dev/null || true
  [[ -z "$backend_pid" ]] || wait "$backend_pid" 2>/dev/null || true
}

trap cleanup EXIT
trap 'exit 130' INT TERM HUP

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker compose up -d db
  node scripts/wait-for-db.mjs
else
  printf '%s\n' '提示：Docker 当前不可用，已跳过本地 PostgreSQL；请确保 backend/.env 指向可用数据库，或设置 DATABASE_ENABLED=false。'
fi

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  python_bin="$PROJECT_DIR/.venv/bin/python"
elif [[ -x "$PROJECT_DIR/backend/.venv/bin/python" ]]; then
  python_bin="$PROJECT_DIR/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_bin="$(command -v python3)"
else
  printf '%s\n' '错误：未找到 Python 3。请先按 README 安装后端依赖。' >&2
  exit 1
fi

if ! "$python_bin" -c 'import uvicorn' >/dev/null 2>&1; then
  printf '%s\n' '错误：当前 Python 环境缺少后端依赖，请先运行 uv sync --project backend。' >&2
  exit 1
fi

if [[ ! -d "$PROJECT_DIR/Agent-frontend/node_modules" ]]; then
  printf '%s\n' '错误：前端依赖尚未安装，请先运行 npm --prefix Agent-frontend ci。' >&2
  exit 1
fi

"$python_bin" -m uvicorn app.main:app \
  --app-dir backend \
  --host 0.0.0.0 \
  --port 3000 \
  --reload \
  --reload-dir backend \
  --reload-exclude 'storage/*' &
backend_pid="$!"

npm --prefix Agent-frontend run dev &
frontend_pid="$!"

printf '%s\n' 'Agent-RS 已启动：前端 http://localhost:5173，后端 http://localhost:3000。按 Ctrl+C 同时停止。'

status=0
while true; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" || status="$?"
    break
  fi
  if ! kill -0 "$frontend_pid" 2>/dev/null; then
    wait "$frontend_pid" || status="$?"
    break
  fi
  sleep 1
done

exit "$status"
