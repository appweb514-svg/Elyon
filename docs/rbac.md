# RBAC — Permissions granulaires

Tout endpoint sensible vérifie `require_permission(Permission.*)` (API) et
`hasPermission(role, perm)` côté front (menu/actions masqués). Les
permissions sont rattachées à un périmètre : `global` (toutes orgs),
`org` (une org), `site` (un site précis via `User.site_id`).

## Rôles

| Rôle | Libellé | Périmètre |
|---|---|---|
| `superadmin` | super-admin | global |
| `org_admin` | admin IT | org |
| `site_manager` | responsable de site | site |
| `operator` | contributeur | site |
| `viewer` (lecteur) | auditeur | site |

`User.site_id` (FK `sites.id`, nullable, SET NULL) scope `site_manager`/
`operator`/`viewer` à un site ; `NULL` = toute l'org.

## Mapping rôle → permissions

Source de vérité : `apps/api/elyon_api/permissions.py` (`ROLE_PERMISSIONS`).

| Permission | superadmin | org_admin | site_manager | operator | viewer |
|---|---|---|:---:|---|---|---|
| `screen.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `screen.create` | ✓ | ✓ | ✓ |  |  |
| `screen.edit` | ✓ | ✓ | ✓ |  |  |
| `screen.delete` | ✓ | ✓ | ✓ |  |  |
| `screen.assign` | ✓ | ✓ | ✓ |  |  |
| `device.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `device.approve` | ✓ | ✓ | ✓ |  |  |
| `device.disable` | ✓ | ✓ | ✓ |  |  |
| `device.command` | ✓ | ✓ | ✓ | ✓ |  |
| `device.update` | ✓ | ✓ | ✓ |  |  |
| `media.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `media.upload` | ✓ | ✓ | ✓ | ✓ |  |
| `media.edit` | ✓ | ✓ | ✓ | ✓ |  |
| `media.delete` | ✓ | ✓ | ✓ |  |  |
| `media.publish` | ✓ | ✓ | ✓ |  |  |
| `playlist.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `playlist.create` | ✓ | ✓ | ✓ | ✓ |  |
| `playlist.edit` | ✓ | ✓ | ✓ | ✓ |  |
| `playlist.delete` | ✓ | ✓ | ✓ |  |  |
| `schedule.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `schedule.create` | ✓ | ✓ | ✓ | ✓ |  |
| `schedule.edit` | ✓ | ✓ | ✓ | ✓ |  |
| `schedule.delete` | ✓ | ✓ | ✓ |  |  |
| `schedule.publish` | ✓ | ✓ | ✓ |  |  |
| `user.view` | ✓ | ✓ | ✓ |  | ✓ |
| `user.create` | ✓ | ✓ |  |  |  |
| `user.edit` | ✓ | ✓ |  |  |  |
| `user.delete` | ✓ | ✓ |  |  |  |
| `audit.view` | ✓ | ✓ | ✓ |  |  |

Front : `apps/web/src/lib/permissions.ts` (`ROLE_PERMISSIONS`, `ROLE_SCOPES`,
`hasPermission`) ; `components/app-shell.tsx` filtre la nav, chaque page
masque les boutons interdits.

## Isolation

- **Org** : tout `SELECT … WHERE org_id == user.org_id` sauf superadmin.
- **Site** : `GET /sites`, `GET /users`, `GET /devices` filtrés par
  `site_id` si renseigné ; `require_site_id_access` sur PATCH/DELETE.
- Tests : `test_rbac_devices_layout.py` (cross-site 403, viewer 403 sur
  mutation, publish audité).

## Audit

`deps.audit()` sur : site/screen/device (create/update/delete/approve/
disable/maintenance/enable/rotate), media (upload/delete), playlist
(create/delete/add_item/remove), schedule (create/update/delete),
manifest.publish, command.issue. `audit.view` réservé aux rôles privilégiés.
