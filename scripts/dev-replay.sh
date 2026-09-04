#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Creating Python venv and installing backend deps..."
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev]"
fi

if [[ ! -x web/node_modules/.bin/vite ]]; then
  echo "Installing frontend deps..."
  (cd web && npm install)
fi

cleanup() {
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

export GAPIQ_IGNORE_ACTIVE_WINDOWS=true
export GAPIQ_PROVIDER=replay
export GAPIQ_ROSTER_FILE=roster.zofingen-2025.json
# Override snapshot, speed, or offset: GAPIQ_REPLAY_SPEED=600 ./scripts/dev-replay.sh

echo "Starting replay API on http://127.0.0.1:8477"
.venv/bin/uvicorn app.main:app --reload --port 8477 &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:8478"
(cd web && npm run dev) &
FRONTEND_PID=$!

wait
