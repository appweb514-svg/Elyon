#!/bin/sh
# Elyon hébergé — stack web uniquement : API + back-office (5140).
# Exposé via Tailscale : https://vps-901.tailda1dd3.ts.net:5140
# Les players émulés sont séparés : run-players.sh (elyon-players.service).
# Dépendances système : poppler-utils (pdftoppm, PDF) et LibreOffice pour les
# documents Office — libreoffice-writer (docx/odt), libreoffice-calc (xlsx/ods),
# libreoffice-impress (pptx/odp). Sans eux, le traitement de ces médias échoue.
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ELYON_LAB_DIR:-$ROOT/.lab/hosted}"
WEB_PORT="${ELYON_WEB_PORT:-5140}"
API_PORT="${ELYON_API_PORT:-8000}"
PY="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
fi

mkdir -p "$LAB/media" "$LAB/enroll"

export ELYON_DATABASE_URL="sqlite:///${LAB}/elyon.db"
export ELYON_MEDIA_STORAGE_ROOT="$LAB/media"
export ELYON_SIGNING_KEY_FILE="$LAB/signing_key.pem"
export ELYON_PUBLIC_BASE_URL="http://127.0.0.1:${API_PORT}"
export ELYON_SESSION_SECRET="${ELYON_SESSION_SECRET:-elyon-hosted-secret}"
export ELYON_ENQUEUE_MEDIA_PROCESSING="false"
export ELYON_PROCESS_MEDIA_INLINE="true"
export ELYON_HEARTBEAT_INTERVAL_SECONDS="5"
export ELYON_AUTO_MIGRATE="true"
export ELYON_API_URL="http://127.0.0.1:${API_PORT}"
export ELYON_COOKIE_SECURE="false"
export PYTHONUNBUFFERED="1"
export ELYON_PUBLIC_WEB_URL="${ELYON_PUBLIC_WEB_URL:-https://vps-901.tailda1dd3.ts.net:${WEB_PORT}}"
# Login désactivé : session ouverte automatiquement avec le compte org admin.
export ELYON_DISABLE_LOGIN="${ELYON_DISABLE_LOGIN:-1}"
export ELYON_AUTO_LOGIN_EMAIL="${ELYON_AUTO_LOGIN_EMAIL:-orgadmin@lab.elyon}"
export ELYON_AUTO_LOGIN_PASSWORD="${ELYON_AUTO_LOGIN_PASSWORD:-elyon-lab-pass}"

log() { printf '\033[1;36m[elyon]\033[0m %s\n' "$*"; }

cleanup() {
  for pidfile in "$LAB"/api.pid "$LAB"/web.pid; do
    if [ -f "$pidfile" ]; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

log "API 127.0.0.1:${API_PORT}"
(
  cd "$ROOT/apps/api"
  exec "$PY" -m uvicorn elyon_api.main:app --host 127.0.0.1 --port "$API_PORT"
) >"$LAB/api.log" 2>&1 &
echo $! >"$LAB/api.pid"

log "Attente de la disponibilité de l'API…"
api_ready=0
for _ in $(seq 1 60); do
  if "$PY" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${API_PORT}/healthz', timeout=2)" >/dev/null 2>&1; then
    api_ready=1
    break
  fi
  sleep 1
done
if [ "$api_ready" -ne 1 ]; then
  log "API indisponible après 60 s"
  exit 1
fi

NEXT="$ROOT/apps/web/node_modules/.bin/next"
if [ ! -x "$NEXT" ]; then
  log "next introuvable — installez les deps web (apps/web/node_modules)"
  exit 1
fi
if [ ! -d "$ROOT/apps/web/.next" ]; then
  log "Build du back-office Next.js…"
  (cd "$ROOT/apps/web" && "$NEXT" build) >"$LAB/web-build.log" 2>&1
fi

log "Web 127.0.0.1:${WEB_PORT}"
(
  cd "$ROOT/apps/web"
  exec "$NEXT" start --port "$WEB_PORT" --hostname 127.0.0.1
) >"$LAB/web.log" 2>&1 &
echo $! >"$LAB/web.pid"

log "Stack web prête — http://127.0.0.1:${WEB_PORT}  (mur : /wall)"
wait "$(cat "$LAB/api.pid")"
