# Raspberry Pi émulés QEMU (vrais systèmes ARM64)

Les players du lab ne sont **pas des simulations** : ce sont de vrais
systèmes Debian Raspberry Pi OS (arm64) démarrés par QEMU (`raspi3b`),
avec le kernel officiel, systemd, l'agent Elyon et le moteur de lecture
mpv — exactement comme un matériel réel.

## Cycle de vie

| Étape | Commande | Résultat |
|---|---|---|
| 1. Construire l'image | `sudo player/qemu/build-image.sh` | `.lab/qemu/elyon-pi.img` (4 Go) |
| 2. Provisionner | Éditer la partition boot de l'image | serial / nom / code d'enrôlement |
| 3. Boot | `player/qemu/run-qemu.sh` | Le Pi boote, s'enrôle, diffuse |
| 4. Extraire | `player/qemu/export-image.sh` | `.img.xz` flashable sur carte SD |

## Provisionnement (partition boot)

L'image expose ses paramètres sur la **partition FAT boot**, éditables
après flash sur une vraie carte SD (ou via losetup pour l'émulateur) :

```
elyon-enroll.code   # code d'enrôlement affiché par le back-office
elyon-serial        # numéro de série déclaré au serveur (unique !)
elyon-name          # nom d'affichage du player
```

Le service `elyon-agent.service` lit ces fichiers au démarrage :
si `state.json` n'existe pas encore, l'agent s'enrôle tout seul
(`--enroll-once`) puis passe en boucle de supervision. La partition
boot est montée sur `/boot` (Bullseye) ou `/boot/firmware` (Bookworm).

## L'agent dans l'image

```
/usr/local/bin/elyon-agent     # agent (enrôlement, heartbeat, commandes)
/usr/local/bin/elyon-playback  # moteur de lecture (mpv)
/usr/local/bin/elyon-enroll    # wrapper d'enrôlement --enroll-once
/usr/local/lib/elyon/          # code source embarqué (agent + playback)
/etc/default/elyon-agent       # ELYON_AGENT_SERVER_URL=http://10.0.2.2:8000
/etc/systemd/system/elyon-{agent,playback}.service
```

Sous QEMU (réseau user-mode), l'hôte est vu à `10.0.2.2` : l'agent
s'y connecte pour le heartbeat/manifeste. Sur un vrai Raspberry Pi,
définissez `ELYON_AGENT_SERVER_URL` sur l'adresse du serveur (fichier
`/etc/default/elyon-agent` ou noyau réseau réel).

## Réseau QEMU

`run-qemu.sh` utilise le réseau user-mode QEMU. L'invité obtient
`10.0.2.15` et voit l'hôte sur `10.0.2.2` — là où écoute l'API Elyon
(`127.0.0.1:8000`). Aucune configuration additionnelle nécessaire.

## Flasher sur un vrai Raspberry Pi

```sh
player/qemu/export-image.sh          # produit .lab/qemu/elyon-pi-export.img.xz
xz -d .lab/qemu/elyon-pi-export.img.xz
# monter la 1re partition pour ajuster serial/code/URL serveur :
#   elyon-enroll.code, elyon-serial, elyon-name
dd if=elyon-pi-export.img of=/dev/sdX bs=4M status=progress oflag=direct
```

Ou avec Raspberry Pi Imager : « Use custom » → `elyon-pi-export.img.xz`.

L'image contient les binaires aarch64 et la configuration système
réelle — elle boote à l'identique sur un Raspberry Pi 3 (et 4 avec le
DTB correspondant).

## Machine émulée

- Modèle : `raspi3b` (QEMU ≥ 6.2, arm64)
- RAM : 1 Go, 4 vCPU (TCG sans KVM — émulation complète du BCM2837)
- Disque : carte SD virtuelle (`mmcblk0`), image raw ext4 + FAT boot
- Console : série `ttyAMA0` (115200), réseau USB RNDIS

## Dépannage

| Symptôme | Cause | Remède |
|---|---|---|
| Pas de sortie console | Bookworm 6.18 livelle en TCG | Garder Bullseye 2023-05-03 (par défaut) |
| `Connection refused` (agent) | Mauvaise variable d'env | `ELYON_AGENT_SERVER_URL` (préfixe `ELYON_AGENT_`) |
| Enrôlement en échec | Code expiré ou serial dupliqué | Régénérer le code, changer `elyon-serial` |
| Image « Can't have a partition outside the disk » | truncate < taille native (2,84 Go) | Garder 4096 Mo par défaut |
| `ModuleNotFoundError: pydantic` | Wheels non extraits | build-image.sh installe les wheels aarch64 |
