import { describe, expect, it } from "vitest";

import { hasPermission, ROLE_PERMISSIONS, ROLE_SCOPES, type Permission, type Role } from "@/lib/permissions";

const ALL_PERMISSIONS: Permission[] = [
  "screen.view", "screen.create", "screen.edit", "screen.delete", "screen.assign",
  "device.view", "device.approve", "device.disable", "device.command", "device.update",
  "media.view", "media.upload", "media.edit", "media.delete", "media.publish",
  "playlist.view", "playlist.create", "playlist.edit", "playlist.delete",
  "schedule.view", "schedule.create", "schedule.edit", "schedule.delete", "schedule.publish",
  "user.view", "user.create", "user.edit", "user.delete",
  "audit.view",
];

describe("hasPermission", () => {
  it("donne toutes les permissions à superadmin", () => {
    for (const perm of ALL_PERMISSIONS) {
      expect(hasPermission("superadmin", perm)).toBe(true);
    }
  });

  it("limite viewer aux lectures", () => {
    expect(hasPermission("viewer", "screen.view")).toBe(true);
    expect(hasPermission("viewer", "device.view")).toBe(true);
    expect(hasPermission("viewer", "screen.edit")).toBe(false);
    expect(hasPermission("viewer", "media.upload")).toBe(false);
    expect(hasPermission("viewer", "user.delete")).toBe(false);
  });

  it("donne à operator les permissions courantes de production sans gestion utilisateurs", () => {
    expect(hasPermission("operator", "media.upload")).toBe(true);
    expect(hasPermission("operator", "schedule.create")).toBe(true);
    expect(hasPermission("operator", "screen.create")).toBe(false);
    expect(hasPermission("operator", "user.view")).toBe(false);
    expect(hasPermission("operator", "audit.view")).toBe(false);
  });

  it("donne à site_manager le périmètre site étendu sans permissions globales", () => {
    expect(hasPermission("site_manager", "screen.assign")).toBe(true);
    expect(hasPermission("site_manager", "device.approve")).toBe(true);
    expect(hasPermission("site_manager", "user.create")).toBe(false);
  });
});

describe("périmètres de rôle", () => {
  it("associe chaque rôle à un périmètre", () => {
    expect(ROLE_SCOPES.superadmin).toBe("global");
    expect(ROLE_SCOPES.org_admin).toBe("org");
    expect(ROLE_SCOPES.site_manager).toBe("site");
    expect(ROLE_SCOPES.operator).toBe("site");
    expect(ROLE_SCOPES.viewer).toBe("site");
  });

  it("définit un ensemble de permissions par rôle", () => {
    for (const role of Object.keys(ROLE_PERMISSIONS) as Role[]) {
      expect(ROLE_PERMISSIONS[role]).toBeInstanceOf(Set);
      expect(ROLE_PERMISSIONS[role].size).toBeGreaterThan(0);
    }
  });
});
