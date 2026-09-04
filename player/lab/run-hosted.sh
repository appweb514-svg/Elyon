#!/bin/sh
# Elyon hébergé (legacy monolithe) : stack web + players émulés.
# Préférer la séparation : run-web.sh (elyon-web.service) +
# run-players.sh (elyon-players.service). Ce wrapper les orchestre.
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
LAB="${ELYON_LAB_DIR:-$ROOT/.lab/hosted}"
API_PORT="${ELYON_API_PORT:-8000}"

"$DIR/run-web.sh" &
web_pid=$!

cleanup_players() {
  for pidfile in "$LAB"/player-1/*.pid "$LAB"/player-2/*.pid "$LAB"/player-preview/*.pid; do
    if [ -f "$pidfile" ]; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
    fi
  done
}
trap cleanup_players EXIT INT TERM

# Attendre que l'API soit en vie avant de lancer les players.
for _ in $(seq 1 90); do
  if [ -f "$LAB/api.pid" ] && kill -0 "$(cat "$LAB/api.pid")" 2>/dev/null; then
    break
  fi
  sleep 1
done

"$DIR/run-players.sh" &
players_pid=$!

wait "$web_pid"
