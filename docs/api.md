# API

Base : `/api` — JSON, auth par cookie de session (`elyon_session`,
httpOnly + CSRF `X-CSRF-Token` sur méthodes non sûres) ou Bearer token
device pour les endpoints player.

## Auth & comptes

| Méthode | Route | Rôle | Description |
|---|---|---|---|
| POST | `/auth/bootstrap` | — | Crée le superadmin initial (403 si déjà fait) |
| POST | `/auth/login` | — | Connexion (rate-limitée par IP), pose les cookies |
| POST | `/auth/logout` | connecté | Invalide la session |
| GET | `/auth/me` | connecté | Profil courant |
| GET/POST | `/organizations` | superadmin | Liste / crée une organisation |
| GET/POST | `/users` | admin | Liste / crée des utilisateurs |
| PATCH | `/users/{id}` | admin | Nom, rôle, activation |

## Sites & écrans

| Méthode | Route | Description |
|---|---|---|
| GET/POST | `/sites` | Sites de l'organisation |
| GET/PATCH/DELETE | `/sites/{id}` | Détail, modification, suppression |
| GET/POST | `/sites/{id}/screens` | Écrans du site |
| PATCH/DELETE | `/screens/{id}` | Modification (dont device_id), suppression |

## Enrôlement & devices

| Méthode | Route | Auth | Description |
|---|---|---|---|
| POST | `/enroll/tokens?site_id=&ttl_seconds=` | admin | Jeton à usage unique (code 6 caractères) |
| POST | `/enroll/request` | — (public) | Enrôlement : serial + name + site_code |
| GET | `/devices` | admin | Liste (statuts pending/approved/blocked) |
| GET | `/devices/{id}` | admin | Détail |
| PATCH | `/devices/{id}` | admin | Nom, site |
| POST | `/devices/{id}/approve` · `/block` · `/rotate-token` | admin | Cycle de vie |
| GET | `/devices/{id}/heartbeat` | admin | Dernier état rapporté |

## Médias

| Méthode | Route | Description |
|---|---|---|
| POST | `/media?name=` | Upload multipart (image/vidéo/PDF), quota par org |
| GET | `/media` · `/media/{id}` | Liste, détail (kind, sha256, dimensions…) |
| GET | `/media/{id}/file` | Fichier original (supporte Range) |
| GET | `/media/{id}/pages/{index}/file` | Page PNG d'un PDF converti |
| DELETE | `/media/{id}` | Suppression |

## Contenu

| Méthode | Route | Description |
|---|---|---|
| GET/POST | `/playlists` · GET/DELETE `/playlists/{id}` | CRUD playlists |
| POST | `/playlists/{id}/items` | Ajout {media_id, duration_seconds} |
| DELETE | `/playlists/{id}/items/{item_id}` | Retrait |
| POST | `/playlists/{id}/reorder` | Ordre absolu (liste d'item_ids) |
| GET/POST | `/schedules` · PATCH/DELETE `/schedules/{id}` | Plannings (site, playlist, fenêtre, priorité) |

## Publication & ops

| Méthode | Route | Auth | Description |
|---|---|---|---|
| POST | `/devices/{id}/publish` | admin | Génère un manifeste signé (version+1) |
| GET | `/devices/{id}/manifest` | device | Dernier manifeste (payload + signature Ed25519) |
| POST | `/devices/{id}/heartbeat` | device | État (state, média courant, stockage libre) |
| GET | `/devices/{id}/commands` | device | Commandes en attente |
| POST | `/devices/{id}/commands` | admin | Envoie reboot/resync/blank/unblank/capture |
| POST | `/devices/{id}/commands/{cmd_id}/ack` | device | Accusé de traitement |
| GET | `/events` | admin | Journal d'événements filtrable |
| GET | `/dashboard` | admin | Compteurs + derniers événements |

## Erreurs

JSON `{"detail": "…"}` ; 401 non authentifié, 403 rôle/hors périmètre,
404 introuvable, 409 conflit, 413 quota dépassé, 429 rate-limit login.
