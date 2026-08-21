#!/usr/bin/env bash
# Assistant de premier démarrage du player Elyon.
#
# À lancer SUR LE PLAYER (écran + clavier, ou SSH) après install-player.sh :
#   1. Configure le Wi-Fi via NetworkManager (optionnel, Ethernet sinon)
#   2. Enrôle le player auprès du serveur (code à 6-8 chiffres fourni
#      par le back-office — l'assistant de l'agent prend le relais en TTY)
#   3. Démarre les services et vérifie l'affichage
#
# Idempotent : chaque étape est sautée si déjà configurée.

set -euo pipefail

DATA_DIR="/var/lib/elyon-player"
VENV="/opt/elyon-player/venv"
SERVICE_USER="elyon"

log() { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
ask() { read -r -p "$1 " answer; echo "$answer"; }

[[ $EUID -eq 0 ]] || { echo "Lancez avec sudo." >&2; exit 1; }

# --- 1. Réseau ---------------------------------------------------------------

if command -v nmcli >/dev/null && nmcli radio wifi | grep -q "enabled"; then
  configure_wifi="n"
  if [[ ! -f /etc/NetworkManager/system-connections/elyon-wifi.nmconnection ]]; then
    configure_wifi=$(ask "Configurer le Wi-Fi maintenant ? [o/N]")
  fi
  if [[ "$configure_wifi" == "o" || "$configure_wifi" == "O" ]]; then
    ssid=$(ask "SSID du réseau Wi-Fi :")
    psk=$(ask "Clé WPA :")
    nmcli dev wifi connect "$ssid" password "$psk" name elyon-wifi
    log "Wi-Fi connecté à '$ssid'."
  fi
else
  log "Pas de Wi-Fi détecté — utilisation du réseau filaire."
fi

log "Test de connectivité…"
server_url=$(grep -h ELYON_AGENT_SERVER_URL /etc/default/elyon-agent 2>/dev/null | cut -d= -f2 || true)
server_url="${server_url:-http://elyon-server.local:8000}"
if ! curl -sf -m 10 "$server_url/healthz" >/dev/null; then
  echo "Serveur injoignable sur $server_url — vérifiez le réseau." >&2
  exit 1
fi
log "Serveur joignable ($server_url)."

# --- 2. Enrôlement -----------------------------------------------------------

if [[ ! -f "$DATA_DIR/state.json" ]]; then
  log "Enrôlement du player — préparez le code d'enrôlement affiché dans le back-office."
  log "(Laissez vide pour utiliser le site par défaut ; suivez les instructions à l'écran.)"
  sudo -u "$SERVICE_USER" \
    ELYON_AGENT_DATA_DIR="$DATA_DIR" \
    ELYON_AGENT_STATE_FILE="$DATA_DIR/state.json" \
    ELYON_AGENT_SERVER_URL="$server_url" \
    "$VENV/bin/python" -m elyon_agent.run --enroll-once </dev/tty >/dev/tty
  log "Enrôlement terminé."
else
  log "Player déjà enrôlé (state.json présent)."
fi

# --- 3. Services ---------------------------------------------------------------

log "Démarrage des services…"
systemctl restart elyon-agent.service
systemctl restart elyon-supervisor.service
sleep 3
systemctl is-active elyon-agent.service >/dev/null || { systemctl status elyon-agent.service --no-pager; exit 1; }
systemctl is-active elyon-supervisor.service >/dev/null || { systemctl status elyon-supervisor.service --no-pager; exit 1; }

log "Player opérationnel :"
log "  - agent       : systemctl status elyon-agent"
log "  - lecture     : systemctl status elyon-supervisor"
log "  - journal     : journalctl -u elyon-agent -f"
log "L'écran doit afficher le contenu publié d'ici quelques secondes."
