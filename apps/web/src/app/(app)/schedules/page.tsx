"use client";

import { useCallback, useEffect, useState } from "react";
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
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Site = { id: string; name: string };
type Playlist = { id: string; name: string };
type Schedule = {
  id: string;
  site_id: string;
  playlist_id: string;
  name: string;
  start_at: string;
  end_at: string;
  priority: number;
  is_active: boolean;
};

export default function SchedulesPage() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [siteId, setSiteId] = useState("");
  const [playlistId, setPlaylistId] = useState("");
  const [priority, setPriority] = useState("0");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");

  const reload = useCallback(async () => {
    try {
      const [scheduleList, siteList, playlistList] = await Promise.all([
        api.get<Schedule[]>("/api/schedules"),
        api.get<Site[]>("/api/sites"),
        api.get<Playlist[]>("/api/playlists"),
      ]);
      setSchedules(scheduleList);
      setSites(siteList);
      setPlaylists(playlistList);
      if (!siteId && siteList.length > 0) {
        setSiteId(siteList[0].id);
      }
      if (!playlistId && playlistList.length > 0) {
        setPlaylistId(playlistList[0].id);
      }
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [siteId, playlistId]);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create() {
    if (!name.trim() || !siteId || !playlistId || !startAt || !endAt) {
      setError("Tous les champs sont requis.");
      return;
    }
    try {
      await api.post("/api/schedules", {
        site_id: siteId,
        playlist_id: playlistId,
        name,
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
        priority: Number.parseInt(priority, 10) || 0,
      });
      setName("");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function toggle(schedule: Schedule) {
    try {
      await api.patch(`/api/schedules/${schedule.id}`, { is_active: !schedule.is_active });
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function remove(schedule: Schedule) {
    if (!window.confirm(`Supprimer le planning « ${schedule.name} » ?`)) return;
    try {
      await api.del(`/api/schedules/${schedule.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  const siteNames = Object.fromEntries(sites.map((s) => [s.id, s.name]));
  const playlistNames = Object.fromEntries(playlists.map((p) => [p.id, p.name]));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Plannings</h1>
      <OrgScopeNotice />
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Nouveau planning</CardTitle>
          <CardDescription>
            Diffuse une playlist sur un site pendant une fenêtre donnée. Priorité plus
            élevée = passe devant les autres plannings actifs.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-6 md:items-end">
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="sc-name">Nom</Label>
            <Input
              id="sc-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Salon des associations"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="sc-site">Site</Label>
            <Select id="sc-site" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="sc-playlist">Playlist</Label>
            <Select
              id="sc-playlist"
              value={playlistId}
              onChange={(e) => setPlaylistId(e.target.value)}
            >
              {playlists.map((playlist) => (
                <option key={playlist.id} value={playlist.id}>
                  {playlist.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="sc-priority">Priorité</Label>
            <Input
              id="sc-priority"
              type="number"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            />
          </div>
          <Button onClick={create}>Créer</Button>
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="sc-start">Début</Label>
            <Input
              id="sc-start"
              type="datetime-local"
              value={startAt}
              onChange={(e) => setStartAt(e.target.value)}
            />
          </div>
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="sc-end">Fin</Label>
            <Input
              id="sc-end"
              type="datetime-local"
              value={endAt}
              onChange={(e) => setEndAt(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tous les plannings</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Site</TableHead>
                <TableHead>Playlist</TableHead>
                <TableHead>Fenêtre</TableHead>
                <TableHead>Priorité</TableHead>
                <TableHead>Actif</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schedules.map((schedule) => (
                <TableRow key={schedule.id}>
                  <TableCell className="font-medium">{schedule.name}</TableCell>
                  <TableCell>{siteNames[schedule.site_id] ?? schedule.site_id}</TableCell>
                  <TableCell>{playlistNames[schedule.playlist_id] ?? schedule.playlist_id}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    {formatDate(schedule.start_at)}
                    <br />→ {formatDate(schedule.end_at)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{schedule.priority}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={schedule.is_active ? "success" : "secondary"}>
                      {schedule.is_active ? "actif" : "inactif"}
                    </Badge>
                  </TableCell>
                  <TableCell className="space-x-2 text-right">
                    <Button size="sm" variant="outline" onClick={() => toggle(schedule)}>
                      {schedule.is_active ? "Désactiver" : "Activer"}
                    </Button>
                    <Button size="sm" variant="destructive" onClick={() => remove(schedule)}>
                      Supprimer
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {schedules.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    Aucun planning.
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
