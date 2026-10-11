#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_ROOT="$REPO_ROOT/apps/api"
WEB_ROOT="$REPO_ROOT/apps/web"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || true)}"
VENV_ROOT="$API_ROOT/.venv"

readonly API_PORT=8002
WEB_PORT=5176

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "需要 Python 3.12。macOS 可运行: brew install python@3.12"
  exit 1
fi

if [[ ! -x "$VENV_ROOT/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_ROOT"
fi

if ! "$VENV_ROOT/bin/python" -c "import fastapi, keyring" >/dev/null 2>&1; then
  "$VENV_ROOT/bin/python" -m pip install -e "$API_ROOT"
fi

if [[ ! -d "$WEB_ROOT/node_modules" ]]; then
  npm --prefix "$WEB_ROOT" install
fi

stop_process() {
  local label="$1"
  local pid="$2"
  local attempts=0

  [[ -z "$pid" ]] && return
  kill -TERM "$pid" 2>/dev/null || return

  while kill -0 "$pid" 2>/dev/null && [[ "$attempts" -lt 30 ]]; do
    sleep 0.1
    attempts=$((attempts + 1))
  done

  if kill -0 "$pid" 2>/dev/null; then
    echo "$label 未在 3 秒内退出，正在强制回收"
    kill -KILL "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  stop_process "前端" "${WEB_PID:-}"
  stop_process "Worker" "${WORKER_PID:-}"
  stop_process "API" "${API_PID:-}"
  exit "$status"
}
trap 'exit 130' INT
trap 'exit 143' TERM
trap cleanup EXIT

(
  cd "$API_ROOT"
  exec "$VENV_ROOT/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT"
) &
API_PID=$!

(
  cd "$API_ROOT"
  exec "$VENV_ROOT/bin/python" -m app.v0.worker
) &
WORKER_PID=$!

(
  cd "$WEB_ROOT"
  VITE_API_TARGET="http://127.0.0.1:$API_PORT" exec npm run dev -- --host 127.0.0.1
) &
WEB_PID=$!

echo "AI Course Studio 脚手架已启动"
echo "前端: http://127.0.0.1:$WEB_PORT"
echo "API:  http://127.0.0.1:$API_PORT/docs"
echo "Worker: 本地独立进程（无端口）"
echo "按 Ctrl+C 停止"

wait "$API_PID" "$WORKER_PID" "$WEB_PID"
