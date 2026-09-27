#!/usr/bin/env bash
# Build the React front-end and place it where the backend serves it from.
#
# After this runs, `uvicorn main:app` (from backend/) serves both the web app
# and the API on a single port — the whole system as one process, one URL.
#
# Usage:
#   ./scripts/build.sh            # build front-end into backend/static
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Building front-end (frontend/ -> dist/)"
cd "$ROOT/frontend"
npm install
npm run build

echo "==> Copying build into backend/static/"
rm -rf "$ROOT/backend/static"
cp -r "$ROOT/frontend/dist" "$ROOT/backend/static"

echo "==> Done."
echo "    Start the server with:"
echo "      cd backend && uvicorn main:app --host 0.0.0.0 --port 5228"
echo "    Then open the front-end at http://<host>:5228/"
