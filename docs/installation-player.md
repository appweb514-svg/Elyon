# Installation player (Raspberry Pi)

## Matériel & OS

- Raspberry Pi 4/5 (2 Go min), carte SD 16 Go+, écran HDMI.
- Raspberry Pi OS Bookworm 64 bits (desktop, auto-login activé).

## Installation

Sur le Pi (ou via SSH) :

```bash
git clone <repo> /opt/elyon-src
cd /opt/elyon-src
sudo ELYON_INSTALLER_SHA256=$(sha256sum player/installer/install-player.sh | cut -d' ' -f1) \
  ./player/installer/install-player.sh https://elyon.exemple.fr
```

Le script installe mpv + Chromium + Python, crée l'utilisateur `elyon`,
prépare `/var/lib/elyon-player`, installe les paquets Python dans
`/opt/elyon-player/venv`, pose les unités systemd et configure le boot
kiosque (veille désactivée).

## Enrôlement

```bash
sudo ./player/setup/setup-wizard.sh
```

1. Wi-Fi optionnel (NetworkManager) puis test de joignabilité du serveur.
2. Saisie du code d'enrôlement affiché dans le back-office
   (Appareils → Générer un jeton d'enrôlement).
3. Dans le back-office : approuver le device, le rattacher à un écran,
   puis « Publier ».

L'écran affiche la boucle en quelques secondes.

## Services

| Service | Rôle |
|---|---|
| `elyon-agent` | heartbeat, commandes, synchronisation des manifestes |
| `elyon-supervisor` | moteur de lecture mpv + watchdog |

```bash
systemctl status elyon-agent        # état
journalctl -u elyon-agent -f        # logs
```

## Validation matérielle (hors CI)

- **Pi 4 et Pi 5** : lecture H.264 1080p fluide (`mpv --hwdec=auto`),
  PDF multi-pages, portrait et paysage.
- **Test continu 24 h** : boucle > 10 000 cycles sans fuite mémoire
  (`systemctl status` → mémoire stable), reprise après coupure réseau
  (la release courante continue), reprise après coupure secteur
  (rollback automatique au démarrage).

## Dépannage

| Symptôme | Vérification |
|---|---|
| Écran noir | `systemctl status elyon-supervisor`, fichier `playback.heartbeat` |
| Pas de sync | `journalctl -u elyon-agent`, clé serveur épinglée (TOFU) |
| Device bloqué | back-office → Appareils → statut, rotate-token si besoin |
