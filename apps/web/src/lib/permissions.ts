export type Permission =
  | "screen.view"
  | "screen.create"
  | "screen.edit"
  | "screen.delete"
  | "screen.assign"
  | "device.view"
  | "device.approve"
  | "device.disable"
  | "device.command"
  | "device.update"
  | "media.view"
  | "media.upload"
  | "media.edit"
  | "media.delete"
  | "media.publish"
  | "playlist.view"
  | "playlist.create"
  | "playlist.edit"
  | "playlist.delete"
  | "schedule.view"
  | "schedule.create"
  | "schedule.edit"
  | "schedule.delete"
  | "schedule.publish"
  | "user.view"
  | "user.create"
  | "user.edit"
  | "user.delete"
  | "audit.view";

export type Role = "superadmin" | "org_admin" | "site_manager" | "operator" | "viewer";

export type Scope = "global" | "org" | "site";

const ALL: Permission[] = [
  "screen.view", "screen.create", "screen.edit", "screen.delete", "screen.assign",
  "device.view", "device.approve", "device.disable", "device.command", "device.update",
  "media.view", "media.upload", "media.edit", "media.delete", "media.publish",
  "playlist.view", "playlist.create", "playlist.edit", "playlist.delete",
  "schedule.view", "schedule.create", "schedule.edit", "schedule.delete", "schedule.publish",
  "user.view", "user.create", "user.edit", "user.delete",
  "audit.view",
];

export const ROLE_PERMISSIONS: Record<Role, Set<Permission>> = {
  superadmin: new Set(ALL),
  org_admin: new Set(ALL),
  site_manager: new Set<Permission>([
    "screen.view", "screen.create", "screen.edit", "screen.delete", "screen.assign",
    "device.view", "device.approve", "device.disable", "device.command", "device.update",
    "media.view", "media.upload", "media.edit", "media.delete", "media.publish",
    "playlist.view", "playlist.create", "playlist.edit", "playlist.delete",
    "schedule.view", "schedule.create", "schedule.edit", "schedule.delete", "schedule.publish",
    "user.view",
    "audit.view",
  ]),
  operator: new Set<Permission>([
    "screen.view",
    "device.view", "device.command",
    "media.view", "media.upload", "media.edit",
    "playlist.view", "playlist.create", "playlist.edit",
    "schedule.view", "schedule.create", "schedule.edit",
  ]),
  viewer: new Set<Permission>([
    "screen.view",
    "device.view",
    "media.view",
    "playlist.view",
    "schedule.view",
    "user.view",
  ]),
};

export const ROLE_SCOPES: Record<Role, Scope> = {
  superadmin: "global",
  org_admin: "org",
  site_manager: "site",
  operator: "site",
  viewer: "site",
};

export function hasPermission(role: Role, perm: Permission): boolean {
  return (ROLE_PERMISSIONS[role] ?? new Set()).has(perm);
}
