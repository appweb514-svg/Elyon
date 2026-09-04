# Elyon — Affichage dynamique centralisé

Elyon est un serveur central multi-utilisateur qui pilote des players Raspberry Pi autonomes : les écrans sont planifiés depuis un back-office web, les contenus (médias, playlists, planning) sont publiés sous forme de manifestes signés et synchronisés sur chaque player, qui reste capable de diffuser même hors ligne.

## Structure du dépôt

- `apps/` — applications serveur :
  - `apps/web` — back-office Next.js (TypeScript)
  - `apps/api` — API FastAPI (Python)
  - `apps/worker` — tâches asynchrones Celery (transcodage, PDF, captures)
- `player/` — logiciel embarqué des Raspberry Pi :
  - `agent` — synchronisation, heartbeat, enrôlement
  - `playback` — moteur de lecture (mpv, images, PDF, Chromium)
  - `setup` — assistant de premier démarrage
  - `systemd` — unités systemd
  - `installer` — script d'installation + vérification de checksum
- `packages/` — bibliothèques partagées :
  - `contracts` — schéma de manifeste, OpenAPI, types TS générés
  - `shared` — utilitaires TS communs front
- `infrastructure/` — `docker`, `proxy`, `database`, `backups`
- `docs/` — documentation technique et ADR (`docs/adr/`)
- `tests/` — tests d'intégration transverses multi-players

## Commandes

- `make lint` — lint Python (ruff) et Web (eslint)
- `make test` — tests Python (pytest) et Web (vitest)
- `make dev` — démarre l'environnement local avec Docker Compose
- `make lab` — API + back-office + 2 Raspberry Pi émulés (enrôlés et publiés)
- `make lab-arm` — idem en `linux/arm64` (QEMU user-mode, comme un Pi 4/5)
- `make lab-local` — même cycle sur l'hôte (sqlite, sans build d'images)
- `make lab-hosted` — back-office sur le port 5140 (dashboard Tailscale)
- `make lab-down` — arrête le lab Docker

Le lab sans matériel est décrit dans `docs/lab.md`.

Statut : lots 0–14 + lab Raspberry émulé.
