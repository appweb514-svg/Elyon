# Architecture

Elyon est une plateforme d'affichage dynamique centralisée : un serveur
central multi-utilisateur est la source de vérité, chaque player Raspberry
Pi garde un cache autonome lui permettant de diffuser hors ligne. La
communication repose sur des manifestes signés Ed25519, une activation
atomique des contenus et un trafic HTTPS sortant uniquement.

## Composants

```
┌──────────────────────────── Serveur ────────────────────────────┐
│  apps/web (Next.js)      apps/api (FastAPI)       worker        │
│  back-office, proxy      REST, RBAC, signatures   traitement    │
│  httpOnly + CSRF         enrôlement, publish      médias/PDF    │
│            └──────── PostgreSQL ────────┘  └── stockage ──┘     │
└─────────────────────────────────────────────────────────────────┘
              ▲ HTTPS sortant uniquement (poll)
┌─────────────┴─────────── Player Raspberry Pi ───────────────────┐
│  elyon-agent (enrôlement, heartbeat, commandes, sync)           │
│  Synchronizer → MediaStore (blobs/, releases/, current→)        │
│  elyon_playback (moteur mpv + superviseur watchdog)             │
└─────────────────────────────────────────────────────────────────┘
```

- **API (`apps/api`)** — FastAPI + SQLAlchemy + PostgreSQL. Auth par
  session cookie httpOnly + CSRF pour le web, tokens Bearer pour les
  devices. RBAC : viewer < manager < org_admin < superadmin. Manifestes
  de diffusion signés Ed25519 (`services/manifest.py`, `signing.py`).
- **Back-office (`apps/web`)** — Next.js App Router, Tailwind + shadcn.
  Le navigateur ne parle jamais à l'API directement : tout passe par un
  proxy `/api/[...elyon]` qui transmet cookies et en-têtes CSRF dans les
  deux sens ; la session API devient la session du back-office.
- **Worker** — conversion PDF → pages PNG, miniatures, métadonnées ;
  les médias passent `uploaded → processing → ready`.
- **Agent player (`player/agent`)** — wizard d'enrôlement (code à usage
  unique), heartbeat, commandes (reboot/resync/blank/unblank/capture),
  vérification TOFU de la clé serveur, téléchargement résumable (Range)
  avec contrôle SHA-256.
- **Sync (`player/agent/sync.py`)** — blobs adressés par contenu,
  releases immuables, activation atomique (fsync + renommage de symlink),
  rollback automatique au démarrage, GC conservant 2 releases.
- **Lecture (`player/playback`)** — file construite depuis le layout
  (priorité desc, schedule_id asc), mpv pour images/vidéos/pages PDF,
  blank asynchrone, superviseur avec watchdog fichier et limite de
  redémarrages.

## Flux de diffusion

1. Un admin crée site → écrans → médias → playlists → plannings.
2. Il génère un jeton d'enrôlement à usage unique ; le player s'enrôle
   (wizard), reste `pending` jusqu'à approbation.
3. L'écran est rattaché au device approuvé, puis « Publier » génère un
   manifeste signé lié au device (device_id, screen_id, version).
4. L'agent récupère le manifeste, vérifie la signature Ed25519 épinglée
   (TOFU), télécharge les blobs manquants, active la release atomiquement.
5. Le moteur lit le layout actif ; hors ligne, la dernière release validée
   continue de tourner.

## Découpage par lots

Lots 0-12 détaillés dans le plan de réalisation : socle (0), modèle (1),
auth/RBAC (2), enrôlement (3), médias (4), playlists/planning (5),
manifestes/publi (6), agent (7), sync résiliente (8), moteur de lecture
(9), back-office (10), installation player (11), durcissement +
intégration multi-player + docs (12).
