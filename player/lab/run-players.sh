#!/bin/sh
# Elyon hébergé — players émulés uniquement (services Linux).
# Exige une API Elyon accessible (défaut http://127.0.0.1:8000,
# surchargeable via ELYON_API_URL ou ELYON_API_PORT).
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ELYON_LAB_DIR:-$ROOT/.lab/hosted}"
API_PORT="${ELYON_API_PORT:-8000}"
API_URL="${ELYON_API_URL:-http://127.0.0.1:${API_PORT}}"
PY="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
fi

mkdir -p "$LAB/enroll" "$LAB/player-1" "$LAB/player-2" "$LAB/player-preview"

log() { printf '\033[1;36m[elyon]\033[0m %s\n' "$*"; }

cleanup() {
  for pidfile in "$LAB"/player-1/*.pid "$LAB"/player-2/*.pid "$LAB"/player-preview/*.pid; do
    if [ -f "$pidfile" ]; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

start_player() {
  serial="$1"
  name="$2"
  data="$3"
  mkdir -p "$data"
  export ELYON_AGENT_SERVER_URL="$API_URL"
  export ELYON_AGENT_SERIAL="$serial"
  export ELYON_AGENT_NAME="$name"
  export ELYON_AGENT_DATA_DIR="$data"
  export ELYON_AGENT_STATE_FILE="$data/state.json"
  export ELYON_AGENT_ENROLL_CODE_FILE="$LAB/enroll/${serial}.code"
  export ELYON_AGENT_ENROLL_WAIT_SECONDS="600"
  export ELYON_PLAYBACK_RENDERER="dummy"
  export ELYON_PLAYBACK_SPEED="1"
  export ELYON_AGENT_COMMAND_POLL_SECONDS="3"
  nohup "$PY" -u -m elyon_playback.engine "$data" >"$data/playback.log" 2>&1 &
  echo $! >"$data/playback.pid"
  nohup "$PY" -u -m elyon_agent.run >"$data/agent.log" 2>&1 &
  echo $! >"$data/agent.pid"
}

start_player emu-rpi-1 "Raspberry émulé 1" "$LAB/player-1"
start_player emu-rpi-2 "Raspberry émulé 2" "$LAB/player-2"
start_player emu-rpi-preview "Aperçu administrateur" "$LAB/player-preview"

log "Bootstrap (idempotent)"
"$PY" "$ROOT/player/lab/bootstrap.py" \
  --api "$API_URL" \
  --enroll-dir "$LAB/enroll" \
  --players 2 \
  --preview

log "Players démarrés (API ${API_URL})"
wait || true
