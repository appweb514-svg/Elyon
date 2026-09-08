# Raspberry Pi — installation d'un player Elyon (Pi 3/4/5)

Transforme un Raspberry Pi OS (Lite ou Desktop, Bookworm recommandé) en
écran Elyon : **agent** (sync, télémétrie, commandes) + **kiosque
Chromium** affichant le player web Elyon.

## 1. Préparer Elyon

1. Dans Elyon, génère un **code d'enrôlement** pour le site cible
   (menu *Pi émulés → Installer*, ou l'écran du site concerné).
2. Astuce : génère **deux codes** si tu veux pairer le kiosque et
   l'agent séparément (les codes sont à usage unique).

## 2. Installer sur le Pi

```bash
curl -fsSL https://<ton-serveur>/deploy/rpi/install.sh | sudo bash
```

Le script installe : agent Python (venv dédié), Chromium, police DejaVu,
mpv, services systemd `elyon-agent` et `elyon-kiosk`.

## 3. Configurer (URL + code)

```bash
sudo elyon-setup
```

Renseigne l'URL du serveur et le code de site. L'agent s'enrôle
automatiquement (appareil `rpi-<serial>` en attente) : approuve-le dans
**Elyon → Appareils**.

## 4. Afficher le contenu

- **Kiosque** : Chromium ouvre `/player` plein écran. Entre le code du
  site **à l'écran** (clavier branché) pour pairer l'affichage, puis
  approuve le device `web-xxxx`.
- **Sans clavier** : colle l'URL avec le token du player dans
  `/etc/elyon/kiosk.env` (`ELYN_PLAYER_URL=https://…/player?token=…`)
  puis `sudo systemctl restart elyon-kiosk`.

## 5. Vérifier

- `systemctl status elyon-agent elyon-kiosk`
- L'appareil apparaît **en ligne** dans Elyon (Appareils, Mur, pi-admin).

## Détails

| Composant | Rôle | Chemin |
|---|---|---|
| `elyon-agent` | heartbeat, commandes (show/stop/reboot), sync manifestes signés | `/opt/elyon-player/venv` |
| `elyon-kiosk` | Chromium plein écran sur le player web | `/etc/elyon/kiosk.env` |
| Données | blobs + releases signés (cache offline) | `/var/lib/elyon-player` |

Lecture vidéo : Chromium lit H.264 (accélération Pi 4/5) ; pour des
formats exotiques, mpv est installé et l'agent bascule dessus.

## Dépannage

- **Agent refuse d'enrôler** : code expiré (TTL 10 min) → régénère.
- **Écran noir** : `journalctl -u elyon-kiosk -f` (X/Chromium), vérifier
  `ELYN_PLAYER_URL`.
- **Accents illisibles** : `fonts-dejavu-core` est requis (installé).
