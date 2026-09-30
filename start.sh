#!/usr/bin/env bash
# Starts Confiance and opens it in your browser. Press Ctrl+C to stop.
set -e
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "Please install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v npm >/dev/null || { echo "Please install Node.js first: https://nodejs.org"; exit 1; }
(cd backend && uv sync --quiet)
[ -d frontend/node_modules ] || (cd frontend && npm install --silent)
(cd backend && uv run uvicorn confiance.api.app:app --port 8000 --log-level warning) &
API=$!
(cd frontend && npm run dev --silent -- --open) &
UI=$!
trap 'kill $API $UI 2>/dev/null' EXIT INT TERM
echo "Confiance is running at http://localhost:5173  (Ctrl+C to stop)"
wait
