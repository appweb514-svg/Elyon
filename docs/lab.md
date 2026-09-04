# Lab — Raspberry Pi émulés

Tester Elyon sans matériel : deux players Debian Bookworm exécutent le
**vrai** agent et le **vrai** moteur, comme sur Raspberry Pi OS. Le rendu
est headless (`DummyRenderer`) : pas d’écran HDMI, l’état courant est
écrit dans `now-playing.json`.

Ce n’est pas une émulation SoC (pas de VideoCore / GPU). Pour coller à
l’architecture Pi 4/5, lancer les mêmes images en `linux/arm64` via QEMU
user-mode (`make lab-arm`).

## Démarrage

```bash
make lab          # Docker : API + web + 2 players
make lab-local    # Sans build d'images : API sqlite + 2 agents + aperçu admin
make lab-hosted   # Back-office 127.0.0.1:5140 + mur VNC, pour le dashboard VPS
```

`make lab` :

1. Démarre PostgreSQL, Redis, API, worker, back-office.
2. Démarre `player-1` et `player-2` (séries `emu-rpi-1` / `emu-rpi-2`).
3. Crée org/site, jetons d’enrôlement, approuve, publie une image démo.
4. Réinitialise le planning de démonstration (`Permanente lab`) : il est réactivé
   et les exclusions locales historiques sont retirées pour les players réels.

Back-office : [http://127.0.0.1:3001](http://127.0.0.1:3001)

`make lab-local` enrôle les mêmes séries contre une API sqlite sur
`http://127.0.0.1:8000` (pas de back-office). Utile quand le build Docker
n’a pas accès à Debian/PyPI.

| Compte | Email | Mot de passe |
|---|---|---|
| Superadmin | `admin@elyon.local` | `elyon-lab-pass` |
| Admin org | `orgadmin@lab.elyon` | `elyon-lab-pass` |

Les players apparaissent **en ligne** après le premier heartbeat, avec le
média démo synchronisé (release `current`). Un troisième player
`emu-rpi-preview` (Aperçu administrateur) reflète le planning **non publié**
: utile pour valider une modification avant « Publier » sur les écrans
réels. Mur type VNC : `/wall`.

Hébergement Tailscale (à ouvrir depuis le navigateur, **pas** `localhost`) :

`https://vps-901.tailda1dd3.ts.net:5140`

(compte `orgadmin@lab.elyon` / `elyon-lab-pass`). Le port 5140 n’écoute
que sur le VPS (`127.0.0.1`) ; Tailscale le publie en HTTPS.

```bash
make lab-logs     # journaux API + players
make lab-down     # stop + volumes
```

## Séparation web / players

La stack web (API + back-office) et les services Linux (players) sont
indépendants, en natif comme en Docker :

| | Stack web seule | + players émulés |
|---|---|---|
| Docker | `docker compose -f compose.yaml up -d` | ajouter `-f compose.lab.yaml` |
| Hôte natif | `make lab-hosted-web` (`player/lab/run-web.sh`) | `make lab-hosted-players` (`player/lab/run-players.sh`) |

En systemd (VPS) : `deploy/elyon-web.service` puis `deploy/elyon-players.service`
(dépend de la stack web). L'unité legacy `deploy/elyon.service` lance le
monolithe via `player/lab/run-hosted.sh`, qui orchestre les deux scripts.

Les players pointent sur l'API via `ELYON_API_URL` (défaut
`http://127.0.0.1:8000`) : ils peuvent donc tourner sur une autre machine
que la stack web.

## Architecture ARM (Pi 4/5)

```bash
docker run --privileged --rm tonistiigi/binfmt --install arm64
make lab-arm
```

Les binaires Python des players tournent alors en aarch64 sous QEMU.

## Commandes à tester depuis le back-office

Sur Appareils → fiche d’un player émulé :

- **Resync** — l’agent retélécharge le manifeste.
- **Blank / Unblank** — pose/retire `/var/lib/elyon-player/blank` ; le moteur
  passe en état `blank` (visible dans `now-playing.json`).
- **Capture** — copie `now-playing.json` dans `captures/`.
- **Reboot** — l’agent quitte ; Docker relance le conteneur (`restart: unless-stopped`).

Inspecter un player :

```bash
docker compose -f compose.yaml -f compose.lab.yaml exec player-1 \
  cat /var/lib/elyon-player/now-playing.json
docker compose -f compose.yaml -f compose.lab.yaml exec player-1 \
  ls -l /var/lib/elyon-player/current
```

## Variables d’un player émulé

| Variable | Rôle |
|---|---|
| `ELYON_AGENT_SERVER_URL` | API (dans Compose : `http://api:8000`) |
| `ELYON_AGENT_SERIAL` | Série stable (`emu-rpi-1`…) |
| `ELYON_AGENT_NAME` | Nom affiché dans le back-office |
| `ELYON_AGENT_ENROLL_CODE_FILE` | Fichier du code d’enrôlement (écrit par le bootstrap) |
| `ELYON_PLAYBACK_RENDERER` | `dummy` en lab ; `mpv` sur un vrai Pi |
| `ELYON_PLAYBACK_SPEED` | Accélération de la boucle dummy (défaut lab : 20) |

Ajouter un 3ᵉ player : dupliquer le service dans `compose.lab.yaml`
(`emu-rpi-3`) puis `make lab` (le bootstrap prend `--players 2` par
défaut ; passer `--players 3` à `player/lab/bootstrap.py`).
