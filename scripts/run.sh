#!/usr/bin/env bash
# Start the API + web app as one detached process (as on the provided server).
# Assumes ./scripts/build.sh has already produced backend/static.
#
# Usage:
#   ./scripts/run.sh [PORT]        # default port 5000 (lab internal; exposed as 5228)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-5000}"

if [ ! -d "$ROOT/backend/static" ]; then
  echo "backend/static not found — run ./scripts/build.sh first." >&2
  exit 1
fi

cd "$ROOT/backend"
echo "==> Starting server on port $PORT (detached via nohup)"
nohup uvicorn main:app --host 0.0.0.0 --port "$PORT" > "$ROOT/server.log" 2>&1 &
echo "    PID $! — logs at $ROOT/server.log"
echo "    Web app:  http://<host>:$PORT/"
echo "    API docs: http://<host>:$PORT/docs"
