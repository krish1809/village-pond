#!/usr/bin/env bash
# Start OpenObserve, the observability backend (logs + traces + metrics) that
# receives OpenTelemetry data from the Village Pond app.
#
# It runs on sys2 on internal port 5000, which the lab forwards externally as
# http://10.1.75.79:5226 (UI + OTLP ingest share that one port). The app on sys4
# sends to it over the internal network at http://172.17.0.27:5000.
#
# Login credentials live in $OO_DIR/oo.env, which is NOT in git:
#   ZO_ROOT_USER_EMAIL=...
#   ZO_ROOT_USER_PASSWORD=...
#
# Usage (on sys2):  bash start_openobserve.sh
set -euo pipefail

OO_DIR="${OO_DIR:-$HOME/openobserve}"
PORT="${PORT:-5000}"
cd "$OO_DIR"

set -a; . "$OO_DIR/oo.env"; set +a
export ZO_HTTP_PORT="$PORT"
export ZO_DATA_DIR="$OO_DIR/data"
export ZO_TELEMETRY=false

# The lab containers are capped at 512 MB of RAM and the box reports 120 CPUs,
# so keep worker pools and in-memory caches deliberately small.
export ZO_HTTP_WORKER_NUM=2
export ZO_MEMORY_CACHE_MAX_SIZE=64
export ZO_MEMORY_CACHE_DATAFUSION_MAX_SIZE=64
export ZO_MEM_TABLE_MAX_SIZE=64
export ZO_MAX_FILE_SIZE_IN_MEMORY=32

# Stop a previous OpenObserve on this port -- and only if it really is ours.
OLD_PID="$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
if [ -n "$OLD_PID" ]; then
  if tr '\0' ' ' < "/proc/$OLD_PID/cmdline" | grep -q openobserve; then
    echo "stopping previous OpenObserve (PID $OLD_PID)"
    kill "$OLD_PID"; sleep 2
  else
    echo "port $PORT is used by something else -- not touching it" >&2
    exit 1
  fi
fi

nohup ./openobserve > "$OO_DIR/openobserve.log" 2>&1 &
echo "OpenObserve started (PID $!), logs: $OO_DIR/openobserve.log"

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    echo "healthy -- UI at http://10.1.75.79:5226/"
    exit 0
  fi
  sleep 1
done
echo "did not become healthy in 30s -- see $OO_DIR/openobserve.log" >&2
exit 1
