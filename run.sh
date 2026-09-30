#!/usr/bin/env bash
# Confiance launcher: sets up everything it needs, starts the app, opens it in your browser.
#
#   ./run.sh                 start (Docker if it is running, otherwise directly on this computer)
#   ./run.sh --docker        force Docker          ./run.sh --native   force a local install
#   ./run.sh --dev           local, with hot-reloading web app on :5173 (for people changing the code)
#   ./run.sh stop            stop it               ./run.sh logs       follow the logs
#   ./run.sh status          is it running?        ./run.sh test       run the backend tests
#
# Environment: PORT (default 8000), NO_BROWSER=1 (do not open a browser tab)
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$PWD
PORT="${PORT:-8000}"
RUN_DIR="$ROOT/.run"; PID_FILE="$RUN_DIR/api.pid"; LOG_FILE="$RUN_DIR/confiance.log"
URL="http://localhost:$PORT"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m  %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

CMD=up; MODE=auto
for a in "$@"; do
  case "$a" in
    up|start) CMD=up ;; stop|down) CMD=stop ;; logs) CMD=logs ;; status) CMD=status ;; test) CMD=test ;;
    --docker) MODE=docker ;; --native) MODE=native ;; --dev) MODE=dev ;;
    -h|--help|help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unknown option '$a'. Try ./run.sh --help" ;;
  esac
done

docker_ready() { have docker && docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; }
compose()      { PORT="$PORT" docker compose "$@"; }
is_up()        { curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; }

wait_up() {
  say "Waiting for Confiance to start..."
  for _ in $(seq 1 120); do is_up && return 0; sleep 1; done
  warn "It did not come up in time. Recent log lines:"
  if [ "$MODE" = docker ]; then compose logs --tail 40 >&2 || true; else tail -n 40 "$LOG_FILE" >&2 || true; fi
  exit 1
}

open_browser() {
  [ "${NO_BROWSER:-}" = 1 ] && return 0
  if have open; then open "$1" >/dev/null 2>&1 || true
  elif have xdg-open; then xdg-open "$1" >/dev/null 2>&1 || true; fi
}

done_banner() {
  echo
  say "Confiance is running:  $URL        (dashboard: $URL/dashboard)"
  echo "    Stop it with:      ./run.sh stop"
  echo "    First time?        Open the dashboard and connect an AI model (Ollama needs no key)."
  [ "$MODE" = docker ] && echo "    Ollama on your computer: use  http://host.docker.internal:11434/v1  as the address."
  open_browser "$URL/dashboard"
}

# ---- Docker path ---------------------------------------------------------------------------------
up_docker() {
  docker_ready || die "Docker is installed but not running (or 'docker compose' is missing). Start Docker Desktop, or use ./run.sh --native"
  is_up && { say "Already running."; done_banner; return; }
  say "Building and starting the container (the first build takes a few minutes)..."
  compose up -d --build
  wait_up; done_banner
}

# ---- Local path ----------------------------------------------------------------------------------
ensure_uv() {
  have uv && return 0
  [ -x "$HOME/.local/bin/uv" ] && { export PATH="$HOME/.local/bin:$PATH"; return 0; }
  say "Installing uv (the Python package manager) from astral.sh..."
  have curl || die "curl is required to install uv. Install it, or install uv yourself: https://docs.astral.sh/uv/"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  export PATH="$HOME/.local/bin:$PATH"
  have uv || die "uv did not install. See https://docs.astral.sh/uv/"
}

ensure_node() {
  have node && have npm && return 0
  if have brew; then say "Installing Node.js with Homebrew..."; brew install node >/dev/null
  elif have apt-get && [ "$(id -u)" = 0 ]; then say "Installing Node.js with apt..."; apt-get install -y nodejs npm >/dev/null
  fi
  have node && have npm || die "Node.js 20+ is required. Install it from https://nodejs.org (or use ./run.sh --docker) and run again."
}

setup_local() {
  ensure_uv; ensure_node
  say "Installing backend dependencies (Python 3.13 is fetched automatically if missing)..."
  (cd backend && uv sync --quiet)
  if [ ! -d frontend/node_modules ] || [ frontend/package-lock.json -nt frontend/node_modules ]; then
    say "Installing web app dependencies..."; (cd frontend && npm ci --silent --no-audit --no-fund)
  fi
}

stop_local() {
  [ -f "$PID_FILE" ] || return 0
  while read -r pid; do kill "$pid" 2>/dev/null || true; done < "$PID_FILE"
  rm -f "$PID_FILE"
}

up_native() {
  is_up && { say "Already running."; done_banner; return; }
  setup_local
  mkdir -p "$RUN_DIR"; : > "$LOG_FILE"; stop_local
  if [ "$MODE" = dev ]; then
    say "Starting the API (:8000) and the hot-reloading web app (:5173)..."
    (cd backend && exec uv run uvicorn confiance.api.app:app --port 8000 --reload --log-level warning) >>"$LOG_FILE" 2>&1 &
    echo $! >> "$PID_FILE"
    (cd frontend && exec npm run dev --silent -- --port 5173) >>"$LOG_FILE" 2>&1 &
    echo $! >> "$PID_FILE"
    PORT=8000 wait_up; URL="http://localhost:5173"
  else
    say "Building the web app..."
    (cd frontend && npm run build --silent)
    say "Starting Confiance on port $PORT..."
    (cd backend && exec uv run uvicorn confiance.api.app:app --port "$PORT" --log-level warning) >>"$LOG_FILE" 2>&1 &
    echo $! >> "$PID_FILE"
    wait_up
  fi
  done_banner
  echo "    Logs: $LOG_FILE   (./run.sh logs)"
  # Stay in the foreground like a dev server: Ctrl+C stops everything.
  trap 'echo; say "Stopping..."; stop_local; exit 0' INT TERM
  while kill -0 "$(head -n1 "$PID_FILE" 2>/dev/null || echo 0)" 2>/dev/null; do sleep 1; done
  warn "The server stopped. See $LOG_FILE"; stop_local; exit 1
}

# ---- Pick a mode -----------------------------------------------------------------------------------
if [ "$MODE" = auto ]; then
  if docker_ready; then MODE=docker; else MODE=native; fi
fi

case "$CMD" in
  up)
    case "$MODE" in docker) up_docker ;; *) up_native ;; esac ;;
  stop)
    if docker_ready && [ -n "$(compose ps -q 2>/dev/null)" ]; then compose down; fi
    stop_local; say "Stopped. Your data is kept (./run.sh again picks up where you left off)." ;;
  logs)
    if docker_ready && [ -n "$(compose ps -q 2>/dev/null)" ]; then compose logs -f --tail 100
    else [ -f "$LOG_FILE" ] && tail -n 100 -f "$LOG_FILE" || die "Nothing is running."; fi ;;
  status)
    if is_up; then say "Running at $URL"; else say "Not running."; exit 1; fi ;;
  test)
    ensure_uv; (cd backend && uv run pytest -q) ;;
esac
