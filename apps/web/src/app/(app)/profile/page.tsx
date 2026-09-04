"use client";

import { useEffect, useState } from "react";
import { api, formatBytes } from "@/lib/api";
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

type Me = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  org_id: string | null;
  team_id: string | null;
  quota_bytes: number;
  created_at: string;
};

type Team = { id: string; name: string; quota_bytes: number; used_bytes: number; members: number };

const ROLE_LABEL: Record<string, string> = {
  superadmin: "Super-administrateur",
  org_admin: "Administrateur",
  site_manager: "Responsable de site",
  operator: "Contributeur",
  viewer: "Lecteur",
};

export default function ProfilePage() {
  const [me, setMe] = useState<Me | null>(null);
  const [team, setTeam] = useState<Team | null>(null);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function reload() {
    try {
      const meData = await api.get<Me>("/api/auth/me");
      setMe(meData);
      setFullName(meData.full_name);
      setEmail(meData.email);
      if (meData.team_id) {
        const teams = await api.get<Team[]>("/api/teams").catch(() => []);
        setTeam(teams.find((t) => t.id === meData.team_id) ?? null);
      } else {
        setTeam(null);
      }
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  useEffect(() => {
    reload();
     
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const patch: Record<string, string> = {};
      if (me && fullName !== me.full_name) patch.full_name = fullName;
      if (me && email !== me.email) patch.email = email;
      if (password) {
        patch.password = password;
        patch.current_password = currentPassword;
      }
      if (Object.keys(patch).length === 0) {
        setNotice("Aucune modification à enregistrer.");
        return;
      }
      await api.patch("/api/auth/me", patch);
      setPassword("");
      setCurrentPassword("");
      if (patch.email) {
        setNotice("Profil mis à jour. Reconnectez-vous avec votre nouvel email.");
      } else {
        setNotice("Profil mis à jour.");
      }
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setSaving(false);
    }
  }

  const quotaLabel = (bytes: number) => (bytes > 0 ? formatBytes(bytes) : "illimité");
  const personalQuota = me?.quota_bytes ?? 0;
  const teamQuota = team?.quota_bytes ?? 0;
  const effective = personalQuota > 0 && teamQuota > 0
    ? Math.min(personalQuota, teamQuota)
    : personalQuota > 0
      ? personalQuota
      : teamQuota;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Mon profil</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Modifiez vos informations personnelles et votre mot de passe.
        </p>
      </div>
      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {notice && <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Informations personnelles</CardTitle>
          <CardDescription>
            Rôle : {ROLE_LABEL[me?.role ?? ""] ?? me?.role} · compte créé le{" "}
            {me ? new Date(me.created_at).toLocaleDateString("fr-FR") : "—"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="profile-name">Nom complet</Label>
            <Input
              id="profile-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-email">Email</Label>
            <Input
              id="profile-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="profile-current">Mot de passe actuel</Label>
              <Input
                id="profile-current"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Requis pour changer le mot de passe"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="profile-password">Nouveau mot de passe</Label>
              <Input
                id="profile-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="12 caractères minimum"
              />
            </div>
          </div>
          <Button onClick={save} disabled={saving || !me}>
            {saving ? "Enregistrement…" : "Enregistrer"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Stockage</CardTitle>
          <CardDescription>
            Quota applicable : le plus restrictif entre votre quota personnel et celui
            de votre équipe.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            Quota personnel : <strong>{quotaLabel(personalQuota)}</strong>
          </p>
          {team ? (
            <>
              <p>
                Équipe : <strong>{team.name}</strong> — {team.members} membre(s)
              </p>
              <p>
                Quota de l&apos;équipe : <strong>{quotaLabel(teamQuota)}</strong> (utilisé :{" "}
                {formatBytes(team.used_bytes)})
              </p>
              <p className="text-muted-foreground">
                Les membres d&apos;une équipe partagent la même bibliothèque de fichiers.
              </p>
            </>
          ) : (
            <p className="text-muted-foreground">
              Vous n&apos;appartenez à aucune équipe : votre bibliothèque est personnelle.
            </p>
          )}
          {effective > 0 && (
            <p className="text-muted-foreground">Plafond effectif : {formatBytes(effective)}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
