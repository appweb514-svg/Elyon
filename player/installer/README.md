# Installer

Script d'installation du player sur Raspberry Pi OS : `install-player.sh`.

```bash
sudo ./player/installer/install-player.sh http://serveur-elyon.local:8000
```

Étapes (idempotent, relançable pour mettre à jour) :

1. Dépendances apt : mpv, chromium-browser + codecs, python3-venv, fonts, NetworkManager.
2. Utilisateur système `elyon` + données dans `/var/lib/elyon-player`.
3. Venv isolé `/opt/elyon-player/venv` avec les paquets `elyon-agent` et `elyon-playback`.
4. Unités systemd installées et activées au démarrage.
5. Boot kiosque via raspi-config (auto-login bureau, veille écran désactivée).
6. Configuration serveur dans `/etc/default/elyon-agent`.

Chaîne de confiance : définir `ELYON_INSTALLER_SHA256=<empreinte>` avant
exécution pour refuser le script si son SHA-256 ne correspond pas.

Ensuite : `sudo ./player/setup/setup-wizard.sh` (réseau + enrôlement).
