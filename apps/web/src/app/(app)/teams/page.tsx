"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatBytes } from "@/lib/api";
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

type Team = {
  id: string;
  name: string;
  org_id: string;
  quota_bytes: number;
  used_bytes: number;
  members: number;
};

type Organization = { id: string; name: string };

function quotaBar(used: number, quota: number) {
  if (quota <= 0) return 0;
  return Math.min(100, Math.round((used / quota) * 100));
}

export default function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [name, setName] = useState("");
  const [quotaGb, setQuotaGb] = useState("");
  const [orgId, setOrgId] = useState("");
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setTeams(await api.get<Team[]>("/api/teams"));
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    reload();
    api.get<Organization[]>("/api/organizations")
      .then(setOrgs)
      .catch(() => undefined);
  }, [reload]);

  async function create() {
    if (!name.trim()) return;
    try {
      const bytes = quotaGb ? Math.round(Number(quotaGb) * 1024 ** 3) : 0;
      await api.post("/api/teams", {
        name: name.trim(),
        quota_bytes: bytes,
        org_id: orgId || null,
      });
      setName("");
      setQuotaGb("");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function updateQuota(team: Team, value: string) {
    const bytes = value === "" ? 0 : Math.max(0, Math.round(Number(value) * 1024 ** 3));
    try {
      await api.patch(`/api/teams/${team.id}`, { quota_bytes: bytes });
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function remove(team: Team) {
    if (!window.confirm(`Supprimer l'équipe « ${team.name} » ?`)) return;
    try {
      await api.del(`/api/teams/${team.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Équipes</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Les membres d&apos;une équipe partagent la même bibliothèque de médias.
          Le quota de l&apos;équipe plafonne l&apos;espace total de ses fichiers (vide ou 0 = illimité).
        </p>
      </div>
      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Nouvelle équipe</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-[2fr_1fr_1fr_1fr] sm:items-end">
          <div className="space-y-2">
            <Label htmlFor="team-name">Nom</Label>
            <Input
              id="team-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Marketing — Gare Nord"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="team-quota">Quota (Go)</Label>
            <Input
              id="team-quota"
              type="number"
              min={0}
              value={quotaGb}
              onChange={(e) => setQuotaGb(e.target.value)}
              placeholder="Illimité"
            />
          </div>
          {orgs.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="team-org">Organisation</Label>
              <Select id="team-org" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">— Choisir —</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </Select>
            </div>
          )}
          <Button onClick={create} disabled={!name.trim()}>
            Créer
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Toutes les équipes ({teams.length})</CardTitle>
          <CardDescription>
            Affectez des membres depuis la page Utilisateurs (champ « Équipe »).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Équipe</TableHead>
                <TableHead>Membres</TableHead>
                <TableHead>Stockage utilisé</TableHead>
                <TableHead>Quota (Go)</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {teams.map((team) => {
                const pct = quotaBar(team.used_bytes, team.quota_bytes);
                return (
                  <TableRow key={team.id}>
                    <TableCell className="font-medium">{team.name}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{team.members}</Badge>
                    </TableCell>
                    <TableCell className="min-w-40">
                      {formatBytes(team.used_bytes)}
                      {team.quota_bytes > 0 && (
                        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                          <div
                            className={
                              "h-full rounded-full transition-all " +
                              (pct >= 95 ? "bg-destructive" : pct >= 75 ? "bg-amber-500" : "bg-emerald-500")
                            }
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Input
                        type="number"
                        min={0}
                        defaultValue={team.quota_bytes ? team.quota_bytes / 1024 ** 3 : ""}
                        placeholder="∞"
                        className="w-24"
                        onBlur={(e) => {
                          const v = e.target.value;
                          const current = team.quota_bytes ? String(team.quota_bytes / 1024 ** 3) : "";
                          if (v !== current) void updateQuota(team, v);
                        }}
                      />
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="destructive" onClick={() => remove(team)}>
                        Supprimer
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {teams.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Aucune équipe — créez la première ci-dessus.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
