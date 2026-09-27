#!/usr/bin/env bash
# Run this ON one of the lab systems (sys1..sys4) to deploy/refresh the app.
#
# The lab boxes are low-storage Docker containers with port-forwarding: the app
# binds to INTERNAL port 5000, which is exposed externally as 5228
# (e.g. http://10.1.75.79:5228/). Dependencies are installed into the system
# Python (no venv) and the compiled front-end is already committed in
# backend/static, so Node/npm is NOT needed here.
#
# It only ever stops OUR server (the process listening on port 5000) — it does
# not touch any other process running on the shared box.
#
# Usage (from the repo root on the box):
#   bash scripts/deploy_on_system.sh
set -euo pipefail

PORT="${PORT:-5000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Use the interpreter that actually has the deps. On the lab systems that's the
# pre-installed conda Python (the system python3 is dep-less); fall back to
# python3 elsewhere. We deliberately do NOT create a venv (saves the ~512 MB /
# small-storage container from a duplicate environment).
if [ -x /opt/conda/bin/python3 ]; then
  PYBIN=/opt/conda/bin/python3
else
  PYBIN=python3
fi
echo "==> Using Python: $PYBIN ($($PYBIN --version 2>&1))"

echo "==> Updating source"
git pull --ff-only || echo "    (git pull skipped/failed — continuing with current checkout)"

echo "==> Checking Python dependencies (no venv, into the existing environment)"
# Phase 3 adds no new deps over Phase 2, so normally everything is already here.
if ! "$PYBIN" -c "import fastapi,uvicorn,numpy,scipy,shapely,pyproj,httpx" 2>/dev/null; then
  echo "    installing missing deps..."
  "$PYBIN" -m pip install -r backend/requirements.txt \
    || "$PYBIN" -m pip install --break-system-packages -r backend/requirements.txt \
    || { echo "!! could not install dependencies" >&2; exit 1; }
else
  echo "    all dependencies already present."
fi

# Find the PID listening on $PORT. lsof isn't installed on the lab boxes, so try
# ss first, then fuser, then lsof — whichever exists.
pid_on_port() {
  ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1 && return 0
  fuser "$PORT"/tcp 2>/dev/null | tr -d ' ' && return 0
  lsof -ti tcp:"$PORT" 2>/dev/null | head -1 && return 0
}

echo "==> Stopping our previous server on port $PORT (only that process)"
OLD_PID="$(pid_on_port || true)"
if [ -n "$OLD_PID" ]; then
  echo "    killing PID $OLD_PID"
  kill $OLD_PID 2>/dev/null || true
  sleep 2
  STILL="$(pid_on_port || true)"
  [ -n "$STILL" ] && { echo "    force-killing $STILL"; kill -9 $STILL 2>/dev/null || true; sleep 1; }
else
  echo "    nothing was listening on $PORT"
fi

echo "==> Starting combined API + web app on port $PORT (detached)"
cd "$ROOT/backend"
nohup "$PYBIN" -m uvicorn main:app --host 0.0.0.0 --port "$PORT" > "$ROOT/server.log" 2>&1 &
NEW_PID=$!
echo "    started PID $NEW_PID (logs: $ROOT/server.log)"

echo "==> Waiting for health check"
for i in $(seq 1 20); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "    healthy."
    curl -s "http://127.0.0.1:$PORT/health"; echo
    echo "==> Done. External URL: http://10.1.75.79:5228/  (docs at /docs)"
    exit 0
  fi
  sleep 1
done

echo "!! Server did not become healthy in time — check $ROOT/server.log" >&2
tail -n 30 "$ROOT/server.log" >&2 || true
exit 1
