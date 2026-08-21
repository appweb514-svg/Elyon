# API

Base : `/api` — JSON, auth par cookie de session (`elyon_session`,
httpOnly + CSRF `X-CSRF-Token` sur méthodes non sûres) ou Bearer token
device pour les endpoints player.

## Auth & comptes

| Méthode | Route | Permission | Description |
|---|---|---|---|
| POST | `/auth/bootstrap` | — | Crée le superadmin initial (403 si déjà fait) |
| POST | `/auth/login` | — | Connexion (rate-limitée par IP), pose les cookies |
| POST | `/auth/logout` | connecté | Invalide la session |
| GET | `/auth/me` | connecté | Profil courant |
| GET/POST | `/organizations` | `superadmin` | Liste / crée une organisation |
| GET | `/users` | `user.view` | Liste filtrée par périmètre |
| POST | `/users` | `user.create` | Crée un utilisateur (`site_id` optionnel pour SITE_MANAGER) |
| PATCH | `/users/{id}` | `user.edit` | Nom, rôle, site, activation |
| DELETE | `/users/{id}` | `user.delete` | Suppression |

Voir `docs/rbac.md` pour le mapping rôle → permissions.

## Sites & écrans

| Méthode | Route | Permission | Description |
|---|---|---|---|
| GET/POST | `/sites` | `screen.view` / `screen.create` | Sites de l'organisation (scopés site si `site_id`) |
| GET/PATCH/DELETE | `/sites/{id}` | view/edit/delete | Détail, modification, suppression |
| GET/POST | `/sites/{id}/screens` | view/create | Écrans du site (→ `ScreenOut.layout` si configuré) |
| PATCH | `/screens/{id}` | `screen.edit` (+ `screen.assign` si `device_id`) | Modification, dont `layout` (ScreenLayout) |
| DELETE | `/screens/{id}` | `screen.delete` | Suppression |

## Enrôlement & devices

| Méthode | Route | Permission / Auth | Description |
|---|---|---|---|
| POST | `/enroll/tokens?site_id=&ttl_seconds=` | `device.view` | Jeton à usage unique (code 6 caractères) |
| POST | `/enroll/request` | — (public) | Enrôlement : serial + name + site_code |
| GET | `/devices` | `device.view` | Liste (computed_status : pending/approved/online/offline/syncing/maintenance/disabled/blocked) |
| GET | `/devices/{id}` | `device.view` | Détail (+ computed_status) |
| PATCH | `/devices/{id}` | `device.view` | Nom, site |
| POST | `/devices/{id}/approve` | `device.approve` | Approbation |
| POST | `/devices/{id}/disable` | `device.disable` | Désactivation (→ disabled) |
| POST | `/devices/{id}/maintenance` | `device.disable` | Maintenance |
| POST | `/devices/{id}/enable` | `device.approve` | Réactivation |
| POST | `/devices/{id}/block` | `device.disable` | Blocage + révocation token |
| POST | `/devices/{id}/rotate-token` | `device.update` | Rotation Bearer |
| GET | `/devices/{id}/heartbeat` | Bearer device | Heartbeat device |
| GET | `/admin/devices/{id}/heartbeat` | `device.view` (admin) | Supervision heartbeat sans Bearer |
| GET | `/admin/devices/{id}/commands` | `device.view` | Historique commandes (admin) |
| GET | `/admin/devices/{id}/manifest` | `device.view` | Aperçu manifeste sans Bearer |
| GET | `/admin/devices/{id}/status` | `device.view` | Statut complet (computed + manifest_version) |

## Médias

| Méthode | Route | Permission | Description |
|---|---|---|---|
| POST | `/media?name=` | `media.upload` | Upload multipart (image/vidéo/PDF), quota par org |
| GET | `/media` · `/media/{id}` | `media.view` | Liste, détail (kind, sha256, dimensions…) |
| GET | `/media/{id}/file` | Bearer device | Fichier original (supporte Range) |
| GET | `/media/{id}/pages/{index}/file` | Bearer device | Page PNG d'un PDF converti |
| DELETE | `/media/{id}` | `media.delete` | Suppression |

## Contenu

| Méthode | Route | Permission | Description |
|---|---|---|---|
| GET/POST | `/playlists` · GET/DELETE `/playlists/{id}` | view/create/delete | CRUD playlists |
| POST | `/playlists/{id}/items` | `playlist.edit` | Ajout {media_id, duration_seconds} |
| DELETE | `/playlists/{id}/items/{item_id}` | `playlist.edit` | Retrait |
| POST | `/playlists/{id}/reorder` | `playlist.edit` | Ordre absolu (liste d'item_ids) |
| GET/POST | `/schedules` · PATCH/DELETE `/schedules/{id}` | view/create/edit/delete | Plannings (site, playlist, fenêtre, priorité) |

## Publication & ops

| Méthode | Route | Permission / Auth | Description |
|---|---|---|---|
| POST | `/devices/{id}/publish` | `schedule.publish` | Génère un manifeste signé (inclut `layout` si configuré) |
| GET | `/devices/{id}/manifest` | Bearer device | Dernier manifeste (payload + signature Ed25519) |
| POST | `/devices/{id}/heartbeat` | Bearer device | État (state, média courant, stockage libre) |
| GET | `/devices/{id}/commands` | Bearer device | Commandes en attente |
| POST | `/devices/{id}/commands` | `device.command` | Envoie reboot/resync/blank/unblank/capture |
| POST | `/devices/{id}/commands/{cmd_id}/ack` | Bearer device | Accusé de traitement |
| GET | `/events` | `device.view` | Journal d'événements filtrable |
| GET | `/dashboard` | `device.view` | Compteurs + derniers événements |
| GET | `/admin/devices/{id}/status` | `device.view` | Voir Enrôlement & devices |

## Erreurs

JSON `{"detail": "…"}` ; 401 non authentifié, 403 rôle/hors périmètre
ou permission manquante, 404 introuvable, 409 conflit, 413 quota
dépassé, 422 validation layout, 429 rate-limit login.
