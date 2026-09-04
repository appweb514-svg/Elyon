#!/bin/sh
# Lab sans images Docker custom : API + 2 players + aperçu admin sur l'hôte.
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ELYON_LAB_DIR:-$ROOT/.lab/local}"
PY="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
fi

mkdir -p "$LAB/media" "$LAB/enroll" "$LAB/player-1" "$LAB/player-2" "$LAB/player-preview"
rm -f "$LAB/elyon.db" "$LAB/player-1/state.json" "$LAB/player-2/state.json" \
  "$LAB/player-preview/state.json"

export ELYON_DATABASE_URL="sqlite:///${LAB}/elyon.db"
export ELYON_MEDIA_STORAGE_ROOT="$LAB/media"
export ELYON_SIGNING_KEY_FILE="$LAB/signing_key.pem"
export ELYON_PUBLIC_BASE_URL="http://127.0.0.1:8000"
export ELYON_SESSION_SECRET="lab-local-secret"
export ELYON_ENQUEUE_MEDIA_PROCESSING="false"
export ELYON_PROCESS_MEDIA_INLINE="true"
export ELYON_HEARTBEAT_INTERVAL_SECONDS="5"
export ELYON_AUTO_MIGRATE="true"

log() { printf '\033[1;36m[lab-local]\033[0m %s\n' "$*"; }

cleanup() {
  for pidfile in "$LAB"/api.pid "$LAB"/web.pid "$LAB"/player-1/*.pid \
    "$LAB"/player-2/*.pid "$LAB"/player-preview/*.pid; do
    if [ -f "$pidfile" ]; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

log "API sur http://127.0.0.1:8000"
(
  cd "$ROOT/apps/api"
  exec "$PY" -m uvicorn elyon_api.main:app --host 127.0.0.1 --port 8000
) >"$LAB/api.log" 2>&1 &
echo $! >"$LAB/api.pid"

start_player() {
  serial="$1"
  name="$2"
  data="$3"
  mkdir -p "$data"
  export ELYON_AGENT_SERVER_URL="http://127.0.0.1:8000"
  export ELYON_AGENT_SERIAL="$serial"
  export ELYON_AGENT_NAME="$name"
  export ELYON_AGENT_DATA_DIR="$data"
  export ELYON_AGENT_STATE_FILE="$data/state.json"
  export ELYON_AGENT_ENROLL_CODE_FILE="$LAB/enroll/${serial}.code"
  export ELYON_AGENT_ENROLL_WAIT_SECONDS="120"
  export ELYON_PLAYBACK_RENDERER="dummy"
  export ELYON_PLAYBACK_SPEED="1"
  export ELYON_AGENT_COMMAND_POLL_SECONDS="3"
  nohup "$PY" -m elyon_playback.engine "$data" >"$data/playback.log" 2>&1 &
  echo $! >"$data/playback.pid"
  nohup "$PY" -m elyon_agent.run >"$data/agent.log" 2>&1 &
  echo $! >"$data/agent.pid"
}

start_player emu-rpi-1 "Raspberry émulé 1" "$LAB/player-1"
start_player emu-rpi-2 "Raspberry émulé 2" "$LAB/player-2"
start_player emu-rpi-preview "Aperçu administrateur" "$LAB/player-preview"

log "Bootstrap org / jetons / publication"
"$PY" "$ROOT/player/lab/bootstrap.py" --api http://127.0.0.1:8000 --enroll-dir "$LAB/enroll"

log "Attente de la lecture dummy (now-playing.json)"
deadline=$(( $(date +%s) + 60 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if grep -q '"state": "playing"' "$LAB/player-1/now-playing.json" 2>/dev/null \
    && grep -q '"state": "playing"' "$LAB/player-2/now-playing.json" 2>/dev/null \
    && grep -q '"state": "playing"' "$LAB/player-preview/now-playing.json" 2>/dev/null; then
    log "Players en lecture :"
    cat "$LAB/player-1/now-playing.json"
    echo
    cat "$LAB/player-2/now-playing.json"
    echo
    log "OK — API : http://127.0.0.1:8000"
    if [ "${ELYON_LAB_ONCE:-}" = "1" ]; then
      exit 0
    fi
    wait "$(cat "$LAB/api.pid")"
    exit 0
  fi
  sleep 1
done

log "Timeout — journaux :"
tail -n 50 "$LAB/api.log" "$LAB/player-1/agent.log" "$LAB/player-2/agent.log" \
  "$LAB/player-preview/agent.log" "$LAB/player-1/playback.log" \
  "$LAB/player-2/playback.log" "$LAB/player-preview/playback.log" || true
exit 1
