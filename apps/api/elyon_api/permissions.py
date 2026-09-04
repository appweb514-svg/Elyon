from __future__ import annotations

import enum

from elyon_api.models import Role


class Permission(enum.StrEnum):
    SCREEN_VIEW = "screen.view"
    SCREEN_CREATE = "screen.create"
    SCREEN_EDIT = "screen.edit"
    SCREEN_DELETE = "screen.delete"
    SCREEN_ASSIGN = "screen.assign"
    DEVICE_VIEW = "device.view"
    DEVICE_APPROVE = "device.approve"
    DEVICE_DISABLE = "device.disable"
    DEVICE_COMMAND = "device.command"
    DEVICE_UPDATE = "device.update"
    MEDIA_VIEW = "media.view"
    MEDIA_UPLOAD = "media.upload"
    MEDIA_EDIT = "media.edit"
    MEDIA_DELETE = "media.delete"
    MEDIA_PUBLISH = "media.publish"
    PLAYLIST_VIEW = "playlist.view"
    PLAYLIST_CREATE = "playlist.create"
    PLAYLIST_EDIT = "playlist.edit"
    PLAYLIST_DELETE = "playlist.delete"
    PLAYLIST_PUBLISH = "playlist.publish"
    SCHEDULE_VIEW = "schedule.view"
    SCHEDULE_CREATE = "schedule.create"
    SCHEDULE_EDIT = "schedule.edit"
    SCHEDULE_DELETE = "schedule.delete"
    SCHEDULE_PUBLISH = "schedule.publish"
    USER_VIEW = "user.view"
    USER_CREATE = "user.create"
    USER_EDIT = "user.edit"
    USER_DELETE = "user.delete"
    AUDIT_VIEW = "audit.view"


ALL: frozenset[Permission] = frozenset(p for p in Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.SUPERADMIN: ALL,
    Role.ORG_ADMIN: ALL,
    Role.SITE_MANAGER: frozenset(
        [
            Permission.SCREEN_VIEW, Permission.SCREEN_CREATE, Permission.SCREEN_EDIT,
            Permission.SCREEN_DELETE, Permission.SCREEN_ASSIGN,
            Permission.DEVICE_VIEW, Permission.DEVICE_APPROVE, Permission.DEVICE_DISABLE,
            Permission.DEVICE_COMMAND, Permission.DEVICE_UPDATE,
            Permission.MEDIA_VIEW, Permission.MEDIA_UPLOAD, Permission.MEDIA_EDIT,
            Permission.MEDIA_DELETE, Permission.MEDIA_PUBLISH,
            Permission.PLAYLIST_VIEW, Permission.PLAYLIST_CREATE, Permission.PLAYLIST_EDIT,
             Permission.PLAYLIST_DELETE, Permission.PLAYLIST_PUBLISH,
             Permission.SCHEDULE_VIEW, Permission.SCHEDULE_CREATE, Permission.SCHEDULE_EDIT,

            Permission.SCHEDULE_DELETE, Permission.SCHEDULE_PUBLISH,
            Permission.USER_VIEW,
            Permission.AUDIT_VIEW,
        ]
    ),
    Role.OPERATOR: frozenset(
        [
            Permission.SCREEN_VIEW,
            Permission.DEVICE_VIEW, Permission.DEVICE_COMMAND,
            Permission.MEDIA_VIEW, Permission.MEDIA_UPLOAD, Permission.MEDIA_EDIT,
            Permission.MEDIA_DELETE,
             Permission.PLAYLIST_VIEW, Permission.PLAYLIST_CREATE, Permission.PLAYLIST_EDIT,
             Permission.PLAYLIST_PUBLISH,
             Permission.SCHEDULE_VIEW, Permission.SCHEDULE_CREATE, Permission.SCHEDULE_EDIT,

        ]
    ),
    Role.VIEWER: frozenset(
        [
            Permission.SCREEN_VIEW,
            Permission.DEVICE_VIEW,
            Permission.MEDIA_VIEW,
            Permission.PLAYLIST_VIEW,
            Permission.SCHEDULE_VIEW,
            Permission.USER_VIEW,
        ]
    ),
}

ROLE_SCOPE: dict[Role, str] = {
    Role.SUPERADMIN: "global",
    Role.ORG_ADMIN: "org",
    Role.SITE_MANAGER: "site",
    Role.OPERATOR: "site",
    Role.VIEWER: "site",
}

# Human-readable mapping for docs/seed
ROLE_PERMISSION_DOC: dict[Role, str] = {
    Role.SUPERADMIN: "Toutes organisations — toutes permissions (global)",
    Role.ORG_ADMIN: "Une organisation — toutes permissions sur son org",
    Role.SITE_MANAGER: "Un site — écran/device/média/playlist/planning + user.view/audit.view",
    Role.OPERATOR: "Un site — view + upload média, édition playlist/planning, commande device",
    Role.VIEWER: "Un site — lecture seule",
}


def has_permission(role: Role, perm: Permission) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, frozenset())
