#!/bin/sh
# Construit une image Raspberry Pi OS Lite (arm64) prête à booter avec
# l'agent Elyon préinstallé. Le player démarre au boot, s'enrôle avec le
# code fourni et affiche le contenu publié — identique au matériel réel.
#
# Usage : sudo player/qemu/build-image.sh [--out DIR]
# Sortie : $OUT/elyon-pi.img (flashable sur une carte SD réelle)
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${ELYON_QEMU_DIR:-$ROOT/.lab/qemu}"
WORK="$OUT/work"
IMG="$OUT/elyon-pi.img"
IMG_SIZE_MB="${ELYON_IMAGE_SIZE_MB:-4096}"
# Image Bullseye 2023-05-03 : dernière version dont le kernel boote de façon
# fiable sous QEMU raspi3b (les kernels récents 6.18+ livellent en TCG).
DOWNLOAD_URL="${ELYON_PIOS_URL:-https://downloads.raspberrypi.org/raspios_lite_arm64/images/raspios_lite_arm64-2023-05-03/2023-05-03-raspios-bullseye-arm64-lite.img.xz}"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    *) echo "Argument inconnu : $1" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "À exécuter avec sudo (mount/losetup requis)" >&2
  exit 1
fi

mkdir -p "$WORK"

echo "[image] téléchargement Raspberry Pi OS Lite arm64…"
XZ="$WORK/raspios.img.xz"
if [ ! -f "$XZ" ] || [ "${ELYON_FORCE_DOWNLOAD:-0}" = "1" ]; then
  curl -fL --retry 3 -o "$XZ" "$DOWNLOAD_URL"
fi

echo "[image] décompression → image de base…"
BASE="$WORK/raspios-base.img"
xz -dk -f -c "$XZ" > "$BASE"

echo "[image] agrandissement à ${IMG_SIZE_MB} Mo…"
truncate -s "${IMG_SIZE_MB}M" "$BASE"
cp "$BASE" "$IMG"

LOOP=$(losetup --find --show --partscan "$IMG")
PART1="${LOOP}p1"
PART2="${LOOP}p2"
echo "[image] loop=$LOOP boot=$PART1 root=$PART2"

cleanup() {
  umount "$WORK/boot" 2>/dev/null || true
  umount "$WORK/root" 2>/dev/null || true
  losetup -d "$LOOP" 2>/dev/null || true
}
trap cleanup EXIT

partprobe "$LOOP" 2>/dev/null || true
sleep 1

echo "[image] extension de la partition root…"
# MBR : la partition 2 s'étire jusqu'au bout du disque agrandi.
parted -s "$IMG" ---pretend-input-is-not-tty print >/dev/null 2>&1 || true
echo "fix" | gdisk "$IMG" >/dev/null 2>&1 || true
parted -s "$IMG" resizepart 2 100% >/dev/null
partprobe "$LOOP" 2>/dev/null || true
partx -u --update 2 "$LOOP" >/dev/null 2>&1 || true
e2fsck -fy "$PART2" >/dev/null 2>&1 || true
resize2fs "$PART2" >/dev/null

mkdir -p "$WORK/boot" "$WORK/root"
mount "$PART2" "$WORK/root"
mount "$PART1" "$WORK/boot"

echo "[image] configuration du premier démarrage headless (mécanisme officiel RPi OS)…"
# 1) utilisateur créé automatiquement au premier boot (sinon userconf-pi attend
#    une interaction à l'infini — cause des boots bloqués sous QEMU).
BOOT_DIR="$WORK/boot/firmware"
[ -d "$BOOT_DIR" ] || BOOT_DIR="$WORK/boot"
HASH=$(chroot "$WORK/root" /usr/bin/openssl passwd -6 "elyon-lab-pass")
echo "elyon:$HASH" > "$BOOT_DIR/userconf.txt"
# 2) firstrun.sh : termine le premier boot sans assistant interactif.
cat > "$BOOT_DIR/firstrun.sh" <<'EOS'
#!/bin/bash
set -eu
# Ne pas relancer l'assistant ni le resize (fait à la construction).
systemctl disable raspi-config 2>/dev/null || true
touch /boot/firmware/ssh
EOS
chmod +x "$BOOT_DIR/firstrun.sh"
touch "$BOOT_DIR/ssh"
# 3) Code d'enrôlement Elyon + identité du player (lisibles/éditables sur la
#    partition boot après flash — comme un vrai provisionnement de carte SD).
echo "000000" > "$BOOT_DIR/elyon-enroll.code"
echo "pi-real" > "$BOOT_DIR/elyon-serial"
echo "Raspberry réel" > "$BOOT_DIR/elyon-name"

echo "[image] préparation chroot (qemu-aarch64-static)…"
cp /usr/bin/qemu-aarch64-static "$WORK/root/usr/bin/"

mkdir -p "$WORK/root/usr/local/lib/elyon/agent_pkg" "$WORK/root/usr/local/lib/elyon/playback_pkg"
cp -r "$ROOT/player/agent/elyon_agent" "$WORK/root/usr/local/lib/elyon/agent_pkg/elyon_agent"
cp -r "$ROOT/player/playback/elyon_playback" "$WORK/root/usr/local/lib/elyon/playback_pkg/elyon_playback"

cat > "$WORK/root/usr/local/bin/elyon-agent" <<'EOS'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/local/lib/elyon/agent_pkg")
from elyon_agent.run import main
main()
EOS

cat > "$WORK/root/usr/local/bin/elyon-playback" <<'EOS'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/local/lib/elyon/playback_pkg")
from elyon_playback.engine import main
main()
EOS
chmod +x "$WORK/root/usr/local/bin/elyon-agent" "$WORK/root/usr/local/bin/elyon-playback"

cat > "$WORK/root/etc/default/elyon-agent" <<'EOS'
ELYON_AGENT_SERVER_URL=http://10.0.2.2:8000
ELYON_AGENT_DATA_DIR=/var/lib/elyon-player
ELYON_AGENT_STATE_FILE=/var/lib/elyon-player/state.json
EOS

# Wrapper : lit serial + nom + code depuis la partition boot, puis enrôle.
cat > "$WORK/root/usr/local/bin/elyon-enroll" <<'EOS'
#!/bin/sh
set -eu
BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot
SERIAL_FILE="$BOOT/elyon-serial"
NAME_FILE="$BOOT/elyon-name"
CODE_FILE="$BOOT/elyon-enroll.code"
SERIAL="pi-real"
[ -s "$SERIAL_FILE" ] && SERIAL="$(cat "$SERIAL_FILE" | tr -d '[:space:]')"
NAME="Raspberry réel"
[ -s "$NAME_FILE" ] && NAME="$(cat "$NAME_FILE" | tr -d '\n')"
export ELYON_AGENT_SERIAL="$SERIAL"
export ELYON_AGENT_NAME="$NAME"
export ELYON_AGENT_ENROLL_CODE_FILE="$CODE_FILE"
export ELYON_AGENT_ENROLL_WAIT_SECONDS=7200
exec /usr/local/bin/elyon-agent --enroll-once
EOS
chmod +x "$WORK/root/usr/local/bin/elyon-enroll"

cat > "$WORK/root/etc/systemd/system/elyon-agent.service" <<'EOS'
[Unit]
Description=Elyon player agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/default/elyon-agent
# Enrôlement : lit serial/nom/code posés sur la partition boot (partition
# montée en /boot/firmware), saute l'assistant interactif, s'enrôle une fois.
ExecStartPre=/bin/sh -c 'if [ ! -f /var/lib/elyon-player/state.json ]; then /usr/local/bin/elyon-enroll; fi'
ExecStart=/usr/local/bin/elyon-agent
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOS

cat > "$WORK/root/etc/systemd/system/elyon-playback.service" <<'EOS'
[Unit]
Description=Elyon playback engine
After=elyon-agent.service
Wants=elyon-agent.service

[Service]
Type=simple
Environment=ELYON_PLAYBACK_RENDERER=mpv
WorkingDirectory=/var/lib/elyon-player
ExecStart=/usr/local/bin/elyon-playback /var/lib/elyon-player
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOS

chroot "$WORK/root" /usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/systemctl enable elyon-agent.service elyon-playback.service

echo "[image] pré-génération du premier boot (accélère énormément QEMU TCG)…"
# machine-id : évite « Detected first boot » (systemd-firstboot très long
# en émulation). Une vraie carte SD régénérera via le même mécanisme.
chroot "$WORK/root" /usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/sh -c 'systemd-machine-id-setup 2>/dev/null || echo "" > /etc/machine-id'
# Clés SSH hôtes générées à la construction (ssh-keygen -A est très coûteux
# sous TCG au premier boot).
chroot "$WORK/root" /usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/sh -c 'ssh-keygen -A 2>/dev/null || true'
# Pas d'attente interactive : l'utilisateur est déjà défini (userconf.txt).
chroot "$WORK/root" /usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/systemctl disable systemd-firstboot.service 2>/dev/null || true
# Réseau : DHCP sur l'interface USB (QEMU) ou eth0 — NetworkManager gère les deux.
chroot "$WORK/root" /usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/sh -c 'nmcli networking on 2>/dev/null || true'

# Dépendances Python de l'agent/playback : wheels aarch64 pré-téléchargés
# (pi dans le chroot QEMU user est extrêmement lent).
echo "[image] installation des dépendances Python (wheels aarch64)…"
WHEELS_DIR="$WORK/wheels"
mkdir -p "$WHEELS_DIR" "$WORK/root/tmp"
if [ ! "$(ls "$WHEELS_DIR"/*.whl 2>/dev/null)" ] || [ "${ELYON_FORCE_DOWNLOAD:-0}" = "1" ]; then
  .venv/bin/pip download httpx pydantic-settings eval_type_backport \
    --platform manylinux2014_aarch64 --platform any \
    --only-binary=:all: --python-version 3.9 \
    -d "$WHEELS_DIR" -q
fi
cp "$WHEELS_DIR"/*.whl "$WORK/root/tmp/"
chroot "$WORK/root" /usr/bin/env -i \
  PATH=/usr/bin:/bin \
  /usr/bin/python3 - <<'EOI' >/dev/null
import zipfile, glob, os
targets = "/usr/local/lib/python3.9/dist-packages"
os.makedirs(targets, exist_ok=True)
for whl in sorted(glob.glob("/tmp/*.whl")):
    with zipfile.ZipFile(whl) as z:
        z.extractall(targets)
os.system("rm -f /tmp/*.whl")
print("wheels installés")
EOI
chroot "$WORK/root" /usr/bin/env -i \
  PATH=/usr/bin:/bin \
  /usr/bin/python3 -c "
import sys
sys.path.insert(0, '/usr/local/lib/elyon/agent_pkg')
import elyon_agent.run, elyon_agent.client
sys.path.insert(0, '/usr/local/lib/elyon/playback_pkg')
import elyon_playback.engine
print('IMPORTS OK')
"

echo "[image] nettoyage…"
rm -f "$WORK/root/usr/bin/qemu-aarch64-static"

echo "[image] OK — $IMG (${IMG_SIZE_MB} Mo, flashable)"
