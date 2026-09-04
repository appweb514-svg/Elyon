"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, formatDate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
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
import { Textarea } from "@/components/ui/textarea";

type Playlist = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  team_id?: string | null;
  team_name?: string | null;
};

export default function PlaylistsPage() {
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  async function reload() {
    try {
      setPlaylists(await api.get<Playlist[]>("/api/playlists"));
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function create() {
    if (!name.trim()) return;
    try {
      await api.post("/api/playlists", {
        name,
        description: description.trim() || null,
      });
      setName("");
      setDescription("");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function remove(playlist: Playlist) {
    if (!window.confirm(`Supprimer la playlist « ${playlist.name} » ?`)) return;
    try {
      await api.del(`/api/playlists/${playlist.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Playlists</h1>
      <OrgScopeNotice />
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Nouvelle playlist</CardTitle>
          <CardDescription>Une séquence ordonnée de médias.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-[2fr_2fr_1fr] sm:items-end">
          <div className="space-y-2">
            <Label htmlFor="pl-name">Nom</Label>
            <Input
              id="pl-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Accueil — boucle matinale"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pl-desc">Description</Label>
            <Textarea
              id="pl-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={1}
            />
          </div>
          <Button onClick={create} disabled={!name.trim()}>
            Créer
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Toutes les playlists</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {playlists.map((playlist) => (
            <div
              key={playlist.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"
            >
              <div>
                <span className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/playlists/${playlist.id}`}
                    className="font-medium hover:underline"
                  >
                    {playlist.name}
                  </Link>
                  {playlist.team_id ? (
                    <Badge variant="secondary">Équipe · {playlist.team_name ?? "—"}</Badge>
                  ) : (
                    <Badge variant="outline">Générale</Badge>
                  )}
                </span>
                {playlist.description && (
                  <p className="text-xs text-muted-foreground">{playlist.description}</p>
                )}
                <p className="text-xs text-muted-foreground">
                  Créée le {formatDate(playlist.created_at)}
                </p>
              </div>
              <Button size="sm" variant="destructive" onClick={() => remove(playlist)}>
                Supprimer
              </Button>
            </div>
          ))}
          {playlists.length === 0 && (
            <p className="text-sm text-muted-foreground">Aucune playlist.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
