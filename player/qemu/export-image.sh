#!/bin/sh
# Extrait une image flashable prête pour un vrai Raspberry Pi (carte SD).
# L'image contient l'OS + l'agent Elyon + le service systemd de démarrage.
#
# Usage : player/qemu/export-image.sh [--out /tmp/elyon-pi.img]
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${ELYON_QEMU_DIR:-$ROOT/.lab/qemu}"
IMG="$OUT/elyon-pi.img"
TARGET="${2:-$OUT/elyon-pi-export.img}"

[ -f "$IMG" ] || { echo "Image absente : $IMG" >&2; exit 1; }

echo "[export] compression de l'image…"
xz -k -c "$IMG" > "${TARGET}.xz"
echo "[export] image prête : ${TARGET}.xz"
echo "[export] flasher sur une carte SD :"
echo "  xz -d ${TARGET}.xz"
echo "  dd if=${TARGET} of=/dev/sdX bs=4M status=progress oflag=direct"
echo "  (remplacez /dev/sdX par le device de la carte SD)"
echo ""
echo "[export] ou avec Raspberry Pi Imager : choisir « Use custom » → ${TARGET}.xz"
