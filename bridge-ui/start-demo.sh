#!/bin/bash
# ============================================
# start-demo.sh — Bridge UI launcher with backend auto-restart
# ============================================
# Single command to bring up the whole demo + keep it up:
#   - Kills any stale process on :8000 / :3002
#   - Starts backend (uvicorn) inside a restart loop so a crash or
#     accidental kill is recovered automatically
#   - Starts frontend (Next.js dev)
#   - Waits until both respond, prints the URL
#   - Ctrl+C stops both cleanly
#
# Usage (Git Bash on Windows or any *nix shell):
#   ./start-demo.sh
#
# Logs:
#   /tmp/bridge-backend.log
#   /tmp/bridge-frontend.log

set -uo pipefail
cd "$(dirname "$0")"

BACKEND_LOG=/tmp/bridge-backend.log
FRONTEND_LOG=/tmp/bridge-frontend.log

# Kill any stale process on the demo ports so a previous half-dead
# server doesn't shadow the new one.
kill_port() {
    local port=$1
    local pid
    pid=$(netstat -ano 2>/dev/null | grep ":$port " | grep LISTENING | awk '{print $5}' | head -1)
    if [ -n "$pid" ]; then
        echo "→ killing stale PID $pid on :$port"
        taskkill //F //PID "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi
}

# ---- Preflight: fail loudly on a fresh clone instead of hanging on dots ----
missing=""
command -v uvicorn >/dev/null 2>&1 || missing="$missing uvicorn"
command -v npm >/dev/null 2>&1 || missing="$missing npm"
[ -d frontend/node_modules ] || missing="$missing frontend/node_modules"
python -c 'import fastapi, numpy, structlog' >/dev/null 2>&1 || missing="$missing python-backend-deps"
if [ -n "$missing" ]; then
    echo "start-demo.sh: missing prerequisites:$missing" >&2
    echo "" >&2
    echo "Fix these, then re-run ./start-demo.sh:" >&2
    echo "  pip install -r backend/requirements.txt   # backend + lub runtime deps" >&2
    echo "  (cd frontend && npm install)              # frontend deps" >&2
    exit 1
fi

echo "Bridge UI — starting..."
kill_port 8000
kill_port 3002

# Backend in a restart loop. If uvicorn dies (crash, accidental kill,
# auto-bot touching a watched file), we wait 2s and bring it back.
# All output goes to BACKEND_LOG so this terminal stays readable.
(
    while true; do
        cd bridge-ui/backend 2>/dev/null || cd backend
        echo "[$(date +%T)] starting uvicorn" >> "$BACKEND_LOG"
        uvicorn server:app --port 8000 --host 127.0.0.1 >> "$BACKEND_LOG" 2>&1
        echo "[$(date +%T)] uvicorn exited — restarting in 2s" >> "$BACKEND_LOG"
        cd - > /dev/null
        sleep 2
    done
) &
BACKEND_LOOP_PID=$!

# Frontend (no restart loop — Next.js dev handles its own reload).
(
    cd bridge-ui/frontend 2>/dev/null || cd frontend
    npm run dev -- -p 3002 >> "$FRONTEND_LOG" 2>&1
) &
FRONTEND_PID=$!

# Cleanup on exit so Ctrl+C kills both halves.
cleanup() {
    echo ""
    echo "Stopping Bridge UI..."
    kill "$BACKEND_LOOP_PID" 2>/dev/null
    kill "$FRONTEND_PID" 2>/dev/null
    kill_port 8000
    kill_port 3002
    exit 0
}
trap cleanup INT TERM

# Wait for both to be ready.
fail_start() {
    echo "" >&2
    echo "start-demo.sh: $1 never came up after 60s — see $2 (last 5 lines):" >&2
    tail -n 5 "$2" 2>/dev/null >&2 || true
    kill "$BACKEND_LOOP_PID" "$FRONTEND_PID" 2>/dev/null
    kill_port 8000; kill_port 3002
    exit 1
}

echo -n "Waiting for backend"
tries=0
until curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; do
    tries=$((tries + 1)); [ "$tries" -ge 60 ] && fail_start "backend" "$BACKEND_LOG"
    echo -n "."
    sleep 1
done
echo " OK"

echo -n "Waiting for frontend"
tries=0
until curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3002 2>/dev/null | grep -q "200"; do
    tries=$((tries + 1)); [ "$tries" -ge 60 ] && fail_start "frontend" "$FRONTEND_LOG"
    echo -n "."
    sleep 1
done
echo " OK"

echo ""
echo "==============================================="
echo "Bridge UI is up:"
echo "  Demo:    http://localhost:3002"
echo "  Backend: http://localhost:8000/health"
echo "  Swagger: http://localhost:8000/docs"
echo ""
echo "  Tip: python scripts/seed-demo.py   # fill the console with demo traffic"
echo ""
echo "Logs:"
echo "  Backend:  $BACKEND_LOG"
echo "  Frontend: $FRONTEND_LOG"
echo ""
echo "Ctrl+C to stop both."
echo "==============================================="

# Block forever; trap handles shutdown.
wait
