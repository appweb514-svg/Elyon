# Page Devices — Supervision et administration

Accès : `GET /devices`, `GET /devices/{id}` (+ computed_status : pending/approved/online/offline/syncing/maintenance/disabled/blocked). Dérivation côté API (`deps.compute_device_status`) : `pending→pending`, `blocked/disabled→tel quel`, `maintenance→maintenance`, `syncing→syncing`, `approved` + heartbeat récent → `online` sinon `offline` (grace 90 s).

## Liste (`/devices`)

- Filtre par périmètre org/site (VIEWER voit sa vue).
- Badges couleur par `computed_status` (syncing/pending = warning).
- Actions : Reboot/Resync (device.command), Approuver (approve), Bloquer/Désactiver/Maintenance (disable), Réactiver (enable), rotation token (update). Boutons masqués selon `hasPermission`.

## Fiche device (`/devices/[id]`)

Trois onglets (données via `/admin/devices/{id}/*` — supervision sans Bearer device) :

1. **Supervision** : statut brut + calculé, dernier heartbeat (`/admin/heartbeat`), écran, version manifeste ; envoi commande (reboot/resync/blank/unblank/capture) ; historique commandes (`/admin/commands`).
2. **Contenu diffusé** : manifeste actif (payload parsé : blocs/priorités, médias), version précédente, média en cours (heartbeat admin), assignation playlist → création d'un planning (30 j, prio 0) puis Publier ; re-sync (resync + publish).
3. **Planning** : plannings du site du device, tri par priorité, détection de conflits (chevauchements → priorité la plus haute gagne, à égalité ID le plus petit), aperçu manifeste.

Toute publication/assignation/commande est auditée (`manifest.publish`, `schedule.create`, `command.issue`).

## Layout

Page dédiée `/devices/[id]/layout` : voir `docs/layout.md`.

## Tests

`test_rbac_devices_layout.py::test_devices_page_accessible_for_all_authorized_roles` (paramétré par rôle), isolation cross-site, non-régression 403 sur viewer.
