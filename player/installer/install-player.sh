#!/usr/bin/env bash
# Installation du player Elyon sur Raspberry Pi OS (Bookworm+).
# Idempotent : peut être relancé sans risque (mises à jour incluses).
#
# Usage :
#   sudo ./install-player.sh [URL_SERVEUR]
#
# Étapes :
#   1. Dépendances système (apt : mpv, chromium-browser, python3-venv…)
#   2. Utilisateur système `elyon` + répertoire de données /var/lib/elyon-player
#   3. Paquets Python agent + moteur de lecture (venv isolé)
#   4. Unités systemd (agent, superviseur) activées au démarrage
#   5. Configuration réseau persistante (NetworkManager, optionnel)
#
# Le script refuse de s'exécuter sans SHA-256 de vérification lorsque
# ELYON_INSTALLER_SHA256 est défini (chaîne de confiance documentée).

set -euo pipefail

SERVER_URL="${1:-http://elyon-server.local:8000}"
DATA_DIR="/var/lib/elyon-player"
INSTALL_ROOT="/opt/elyon-player"
SERVICE_USER="elyon"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

log() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[erreur]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 0. Préconditions -------------------------------------------------------

[[ $EUID -eq 0 ]] || die "Lancez avec sudo (installation système)."

if [[ -n "${ELYON_INSTALLER_SHA256:-}" ]]; then
  actual="$(sha256sum "$0" | awk '{print $1}')"
  [[ "$actual" == "$ELYON_INSTALLER_SHA256" ]] || die "Empreinte SHA-256 invalide (attendue: $ELYON_INSTALLER_SHA256, obtenue: $actual)"
  log "Empreinte SHA-256 vérifiée."
fi

command -v apt-get >/dev/null || die "apt-get introuvable — Raspberry Pi OS requis."
arch="$(dpkg --print-architecture)"
[[ "$arch" == "arm64" || "$arch" == "armhf" ]] || log "Attention : architecture $arch non testée (cible : Raspberry Pi)."

# --- 1. Dépendances système --------------------------------------------------

log "Installation des dépendances système (mpv, chromium, python)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  mpv \
  chromium-browser chromium-codecs-ffmpeg-extra \
  python3 python3-venv python3-pip \
  fonts-noto-color-emoji \
  network-manager \
  >/dev/null

# --- 2. Utilisateur + répertoires --------------------------------------------

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  log "Création de l'utilisateur système $SERVICE_USER…"
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR" "$DATA_DIR/blobs"
install -d "$INSTALL_ROOT"

# --- 3. Paquets Python (agent + lecture) --------------------------------------

log "Installation des paquets Python (agent, moteur de lecture)…"
python3 -m venv "$INSTALL_ROOT/venv"
"$INSTALL_ROOT/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_ROOT/venv/bin/pip" install --quiet "$REPO_ROOT/player/agent" "$REPO_ROOT/player/playback"

chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_ROOT"

# --- 4. Unités systemd --------------------------------------------------------

log "Installation des unités systemd…"
install -m 0644 "$REPO_ROOT/player/systemd/elyon-supervisor.service" /etc/systemd/system/
install -m 0644 "$REPO_ROOT/player/systemd/elyon-agent.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable elyon-agent.service elyon-supervisor.service >/dev/null

# --- 5. Boot kiosque (console auto-login → non interactif) -------------------

log "Configuration du boot kiosque…"
raspi_config_nonint() {
  if command -v raspi-config >/dev/null; then
    raspi-config nonint "$1" "$2" || true
  fi
}
raspi_config_nonint do_boot_behaviour B4  # B4 = desktop auto-login
raspi_config_nonint do_blanking 1         # 1 = désactive la mise en veille écran

# --- 6. Configuration de démarrage --------------------------------------------

if [[ ! -f /etc/default/elyon-agent ]]; then
  log "Écriture de la configuration initiale (/etc/default/elyon-agent)…"
  cat > /etc/default/elyon-agent <<EOF
ELYON_AGENT_SERVER_URL=$SERVER_URL
EOF
  chmod 0644 /etc/default/elyon-agent
fi

log "Démarrage des services…"
systemctl restart elyon-agent.service
systemctl restart elyon-supervisor.service

log "Installation terminée."
log "Prochaine étape : lancez player/setup/setup-wizard.sh pour configurer le réseau et enrôler le player."
