#!/bin/sh
# Démarre le moteur de lecture puis l'agent (même couple que systemd sur le Pi).
set -eu

DATA="${ELYON_AGENT_DATA_DIR:-/var/lib/elyon-player}"
mkdir -p "$DATA"

python -m elyon_playback.supervisor "$DATA" &
exec python -m elyon_agent.run
