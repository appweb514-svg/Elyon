#!/usr/bin/env bash
# Installation d'un player Elyon sur Raspberry Pi OS (Pi 3/4/5).
#
#   curl -fsSL https://<ton-serveur>/deploy/rpi/install.sh | sudo bash
#
# Installe : agent Elyon (sync/télémétrie/commandes) + Chromium kiosque
# pointé sur le player web. La configuration (URL + code de site) se fait
# ensuite via `sudo elyon-setup`, directement sur le Pi (console/SSH) ou
# à l'écran si un clavier est branché.
set -euo pipefail

ELYON_USER="elyon"
ELYON_ROOT="/opt/elyon-player"
ELYON_DATA="/var/lib/elyon-player"
REPO_URL="${ELYON_REPO_URL:-https://github.com/appweb514-svg/Elyon.git}"
REPO_BRANCH="${ELYON_REPO_BRANCH:-feature/emulate-raspberry-pi-1cc}"

[[ $EUID -eq 0 ]] || { echo "À exécuter en root (sudo)"; exit 1; }

echo "==> Dépendances système"
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv git chromium fonts-dejavu-core \
  mpv unclutter

echo "==> Utilisateur ${ELYON_USER}"
id -u "${ELYON_USER}" &>/dev/null || useradd --system --create-home --home-dir "${ELYON_DATA}" "${ELYON_USER}"
mkdir -p "${ELYON_DATA}" "${ELYON_ROOT}"
chown -R "${ELYON_USER}:${ELYON_USER}" "${ELYON_DATA}"

echo "==> Code du player (agent + moteur)"
if [[ -d "${ELYON_ROOT}/src/.git" ]]; then
  git -C "${ELYON_ROOT}/src" fetch --depth 1 origin "${REPO_BRANCH}"
  git -C "${ELYON_ROOT}/src" reset --hard FETCH_HEAD
else
  git clone --depth 1 --branch "${REPO_BRANCH}" "${REPO_URL}" "${ELYON_ROOT}/src"
fi

echo "==> Environnement Python (vhost ${ELYON_ROOT}/venv)"
python3 -m venv "${ELYON_ROOT}/venv"
"${ELYON_ROOT}/venv/bin/pip" install --quiet --upgrade pip
"${ELYON_ROOT}/venv/bin/pip" install --quiet \
  "httpx>=0.27" "cryptography>=42" "pydantic-settings>=2" "Pillow>=10.0" \
  -e "${ELYON_ROOT}/src/player/agent" -e "${ELYON_ROOT}/src/player/playback"

echo "==> Services systemd"
cat > /etc/systemd/system/elyon-agent.service <<UNIT
[Unit]
Description=Elyon player agent
After=network-online.target
Wants=network-online.target

[Service]
User=${ELYON_USER}
EnvironmentFile=-/etc/elyon/player.env
ExecStart=${ELYON_ROOT}/venv/bin/python -m elyon_agent.run ${ELYON_DATA}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/elyon-kiosk.service <<UNIT
[Unit]
Description=Elyon kiosk (Chromium, player web)
After=elyon-agent.service graphical.target
Wants=elyon-agent.service

[Service]
User=${ELYON_USER}
EnvironmentFile=-/etc/elyon/kiosk.env
ExecStartPre=/usr/bin/xauth add :0 . /home/${ELYON_USER}/.Xauthority
ExecStart=/usr/bin/chromium --kiosk --noerrdialogs --disable-infobars \\
  --disable-session-crashed-bubble --start-fullscreen $ELyonUrlPlaceholder
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
UNIT

mkdir -p /etc/elyon
touch /etc/elyon/player.env /etc/elyon/kiosk.env
chmod 600 /etc/elyon/*.env

cat > /usr/local/bin/elyon-setup <<'SETUP'
#!/usr/bin/env bash
# Configuration interactive : URL du serveur + code d'enrôlement du site.
set -euo pipefail
read -rp "URL du serveur Elyon (ex. https://elyon.exemple.fr) : " URL
read -rp "Code d'enrôlement du site (ex. 7DF6D2) : " CODE
SERIAL="rpi-$(cat /proc/device-tree/serial-number 2>/dev/null | tr -d '\0' | tail -c 9 || echo "$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')")"
cat > /etc/elyon/player.env <<ENV
ELYON_AGENT_SERVER_URL=${URL%/}
ELYON_AGENT_SERIAL=${SERIAL}
ELYON_AGENT_NAME=Raspberry ${SERIAL}
ELYON_AGENT_ENROLL_CODE=${CODE}
ENV
cat > /etc/elyon/kiosk.env <<ENV
ELYN_PLAYER_URL=${URL%/}/player
ENV
systemctl restart elyon-agent
systemctl enable --now elyon-kiosk 2>/dev/null || true
echo
echo "Écran configuré (${SERIAL})."
echo " - L'agent s'enrôle automatiquement (approuve-le dans Elyon → Appareils)."
echo " - Le kiosque ouvre /player : entre le code du site à l'écran (2e code)"
echo "   pour afficher le contenu, ou colle l'URL avec ?token=… "
SETUP
chmod +x /usr/local/bin/elyon-setup

systemctl daemon-reload
systemctl enable elyon-agent 2>/dev/null || true

echo
echo "✔ Installation terminée."
echo "  1. Génère un code d'enrôlement dans Elyon (site / lab)."
echo "  2. Lance : sudo elyon-setup   (URL + code)"
echo "  3. Approuve l'appareil dans Elyon → Appareils."
