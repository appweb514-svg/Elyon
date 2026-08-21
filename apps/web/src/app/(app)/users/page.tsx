"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatDate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { hasPermission } from "@/lib/permissions";

type User = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  org_id: string | null;
  site_id: string | null;
  created_at: string;
};

type Organization = { id: string; name: string; slug: string; quota_bytes: number };
type Site = { id: string; name: string };

type Me = { id: string; role: string; org_id: string | null; site_id: string | null };

const ROLE_LABEL: Record<string, string> = {
  superadmin: "super-admin",
  org_admin: "admin IT",
  site_manager: "responsable de site",
  operator: "contributeur",
  viewer: "lecteur",
};

const ROLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "viewer", label: "lecteur (viewer)" },
  { value: "operator", label: "contributeur (operator)" },
  { value: "site_manager", label: "responsable de site (site_manager)" },
  { value: "org_admin", label: "admin IT (org_admin)" },
];

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");
  const [orgId, setOrgId] = useState("");
  const [siteId, setSiteId] = useState("");

  const reload = useCallback(async () => {
    try {
      const [meData, userList] = await Promise.all([
        api.get<Me>("/api/auth/me"),
        api.get<User[]>("/api/users"),
      ]);
      setMe(meData);
      setUsers(userList);
      if (meData.role === "superadmin") {
        const orgList = await api.get<Organization[]>("/api/organizations");
        setOrgs(orgList);
      }
      if (meData.role === "superadmin" || meData.role === "org_admin") {
        const siteList = await api.get<Site[]>("/api/sites").catch(() => [] as Site[]);
        setSites(siteList as Site[]);
      }
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function create() {
    if (!email.trim() || !fullName.trim() || password.length < 12) {
      setError("E-mail, nom complet et mot de passe (12+ caractères) requis.");
      return;
    }
    try {
      await api.post("/api/users", {
        email,
        full_name: fullName,
        password,
        role,
        org_id: orgId || null,
        site_id: siteId || null,
      });
      setEmail("");
      setFullName("");
      setPassword("");
      setSiteId("");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function patchUser(user: User, body: Record<string, unknown>) {
    try {
      await api.patch(`/api/users/${user.id}`, body);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function deleteUser(user: User) {
    if (!window.confirm(`Supprimer ${user.full_name} (${user.email}) ?`)) return;
    try {
      await api.del(`/api/users/${user.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  const orgNames = Object.fromEntries(orgs.map((o) => [o.id, o.name]));
  const siteNames = Object.fromEntries(sites.map((s) => [s.id, s.name]));
  const isSuperadmin = me?.role === "superadmin";
  const canCreate = me ? hasPermission(me.role as never, "user.create" as never) : false;
  const canEdit = me ? hasPermission(me.role as never, "user.edit" as never) : false;
  const canDelete = me ? hasPermission(me.role as never, "user.delete" as never) : false;
  const showSiteSelect = role === "site_manager" || role === "operator" || role === "viewer";
  const filteredSites = orgId ? sites.filter((s) => s.id && (orgs.find((o) => o.id === orgId) ? true : true)) : sites;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Utilisateurs</h1>
      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

      {canCreate && (
        <Card>
          <CardHeader>
            <CardTitle>Nouvel utilisateur</CardTitle>
            <CardDescription>
              Rôles : lecteur, contributeur, responsable de site, admin IT, super-admin.
              Les responsables/contributeurs/lecteurs peuvent être rattachés à un site précis.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-6 md:items-end">
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="u-email">E-mail</Label>
              <Input
                id="u-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="u-name">Nom complet</Label>
              <Input
                id="u-name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="u-password">Mot de passe</Label>
              <Input
                id="u-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={12}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="u-role">Rôle</Label>
              <Select id="u-role" value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
                {isSuperadmin && <option value="superadmin">super-admin</option>}
              </Select>
            </div>
            {isSuperadmin && (
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="u-org">Organisation</Label>
                <Select id="u-org" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  <option value="">— Aucune (superadmin) —</option>
                  {orgs.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            {showSiteSelect && sites.length > 0 && (
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="u-site">Site (optionnel)</Label>
                <Select id="u-site" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
                  <option value="">— Aucun (toute l&apos;org) —</option>
                  {filteredSites.map((site) => (
                    <option key={site.id} value={site.id}>
                      {site.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <Button onClick={create} className="md:col-span-2">
              Créer
            </Button>
          </CardContent>
        </Card>
      )}

      {isSuperadmin && orgs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Organisations</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              {orgs.map((org) => (
                <li key={org.id}>
                  <span className="font-medium">{org.name}</span>{" "}
                  <span className="text-muted-foreground">
                    ({org.slug} — quota {Math.round(org.quota_bytes / 1024 ** 3)} Go)
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Tous les utilisateurs</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Utilisateur</TableHead>
                <TableHead>Rôle</TableHead>
                <TableHead>Organisation / Site</TableHead>
                <TableHead>Créé le</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="font-medium">{user.full_name}</div>
                    <div className="text-xs text-muted-foreground">{user.email}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={user.role === "superadmin" ? "default" : "secondary"}>
                      {ROLE_LABEL[user.role] ?? user.role}
                    </Badge>
                    {!user.is_active && <Badge variant="destructive">inactif</Badge>}
                  </TableCell>
                  <TableCell className="text-xs">
                    <div>{user.org_id ? (orgNames[user.org_id] ?? user.org_id) : "—"}</div>
                    {user.site_id && (
                      <div className="text-muted-foreground">
                        Site : {siteNames[user.site_id] ?? user.site_id}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>{formatDate(user.created_at)}</TableCell>
                  <TableCell className="space-x-1 text-right">
                    {canEdit && user.id !== me?.id && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => patchUser(user, { is_active: !user.is_active })}
                      >
                        {user.is_active ? "Désactiver" : "Réactiver"}
                      </Button>
                    )}
                    {canDelete && user.id !== me?.id && (
                      <Button size="sm" variant="destructive" onClick={() => deleteUser(user)}>
                        Supprimer
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
