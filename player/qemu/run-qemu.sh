#!/bin/sh
# Démarre un vrai Raspberry Pi émulé (QEMU raspi3b, kernel arm64 réel du
# Raspberry Pi OS) et le connecte au réseau du serveur Elyon.
#
# Réseau user-mode QEMU : l'invité voit l'hôte sur 10.0.2.2, c'est l'URL du
# serveur configurée dans /etc/default/elyon-agent de l'image.
#
# Usage : player/qemu/run-qemu.sh
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${ELYON_QEMU_DIR:-$ROOT/.lab/qemu}"
IMG="$OUT/elyon-pi.img"
KERNEL="$OUT/kernel8.img"
DTB="$OUT/bcm2710-rpi-3-b.dtb"

[ -f "$IMG" ]    || { echo "Image absente : $IMG (build-image.sh)" >&2; exit 1; }
[ -f "$KERNEL" ] || { echo "Kernel absent : $KERNEL" >&2; exit 1; }
[ -f "$DTB" ]    || { echo "DTB absent : $DTB" >&2; exit 1; }

echo "[qemu] boot raspi3b — API sur 10.0.2.2:8000 (hôte)"
exec qemu-system-aarch64 \
  -M raspi3b \
  -kernel "$KERNEL" \
  -dtb "$DTB" \
  -drive "file=$IMG,format=raw,if=sd" \
  -append "rw root=/dev/mmcblk0p2 rootwait console=ttyAMA1,115200 console=ttyAMA0,115200" \
  -m 1024 \
  -smp 4 \
  -nographic \
  -serial mon:stdio \
  -usb -device usb-kbd -device usb-tablet \
  -netdev user,id=net0 \
  -device usb-net,netdev=net0
