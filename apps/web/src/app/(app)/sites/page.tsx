"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, formatDate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { OrgScopeNotice } from "@/components/org-scope-notice";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Site = {
  id: string;
  name: string;
  timezone: string;
  address: string | null;
  created_at: string;
};

export default function SitesPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("Europe/Paris");

  const reload = useCallback(async () => {
    try {
      setSites(await api.get<Site[]>("/api/sites"));
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function create() {
    if (!name.trim()) return;
    try {
      await api.post("/api/sites", { name, timezone: timezone || "Europe/Paris" });
      setName("");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function remove(site: Site) {
    if (!window.confirm(`Supprimer le site « ${site.name} » et ses écrans ?`)) return;
    try {
      await api.del(`/api/sites/${site.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Sites & écrans</h1>
      <OrgScopeNotice />
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Nouveau site</CardTitle>
          <CardDescription>
            Un site regroupe des écrans et sert de cible aux plannings.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-[2fr_1fr_1fr] sm:items-end">
          <div className="space-y-2">
            <Label htmlFor="site-name">Nom</Label>
            <Input
              id="site-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Mairie — accueil"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="site-tz">Fuseau horaire</Label>
            <Input
              id="site-tz"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="Europe/Paris"
            />
          </div>
          <Button onClick={create} disabled={!name.trim()}>
            Créer
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tous les sites</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {sites.map((site) => (
            <div
              key={site.id}
              className="flex items-center justify-between rounded-md border p-3"
            >
              <div>
                <Link href={`/sites/${site.id}`} className="font-medium hover:underline">
                  {site.name}
                </Link>
                <p className="text-xs text-muted-foreground">
                  {site.timezone} · créé le {formatDate(site.created_at)}
                </p>
              </div>
              <Button size="sm" variant="destructive" onClick={() => remove(site)}>
                Supprimer
              </Button>
            </div>
          ))}
          {sites.length === 0 && (
            <p className="text-sm text-muted-foreground">Aucun site.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
