"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LayoutEditor, type ScreenLayout } from "@/components/layout-editor";

type Device = {
  id: string;
  name: string;
  serial: string;
  status: string;
  computed_status?: string | null;
  site_id: string | null;
  screen_id: string | null;
  last_seen_at: string | null;
  created_at: string;
};

type AdminStatus = {
  device_id: string;
  status: string;
  computed_status: string;
  last_seen_at: string | null;
  screen_id: string | null;
  manifest_version: number | null;
};

type Screen = {
  id: string;
  site_id: string;
  name: string;
  width: number;
  height: number;
  orientation: string;
  device_id: string | null;
  layout?: ScreenLayout | null;
};

type Site = { id: string; name: string };
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
type Playlist = { id: string; name: string };
type Media = { id: string; name: string; kind: string };

const STATUS_LABEL: Record<string, string> = {
  pending: "en attente",
  approved: "approuvé",
  online: "en ligne",
  offline: "hors ligne",
  syncing: "synchronisation",
  maintenance: "maintenance",
  disabled: "désactivé",
  blocked: "bloqué",
};

function statusVariant(s: string): "success" | "warning" | "destructive" | "secondary" {
  if (s === "online" || s === "approved") return "success";
  if (s === "pending" || s === "syncing") return "warning";
  if (s === "blocked" || s === "disabled") return "destructive";
  return "secondary";
}

export default function DeviceLayoutPage() {
  const params = useParams<{ id: string }>();
  const deviceId = params.id;
  const [device, setDevice] = useState<Device | null>(null);
  const [screen, setScreen] = useState<Screen | null>(null);
  const [site, setSite] = useState<Site | null>(null);
  const [adminStatus, setAdminStatus] = useState<AdminStatus | null>(null);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [mediaList, setMediaList] = useState<Media[]>([]);
  const [layoutDraft, setLayoutDraft] = useState<ScreenLayout | null>(null);
  const [manifest, setManifest] = useState<{ version: number; payload: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const dev = await api.get<Device>(`/api/devices/${deviceId}`);
      setDevice(dev);
      const status = await api
        .get<AdminStatus>(`/api/admin/devices/${deviceId}/status`)
        .catch(() => null);
      setAdminStatus(status);
      const mf = await api
        .get<{ version: number; payload: string }>(`/api/admin/devices/${deviceId}/manifest`)
        .catch(() => null);
      setManifest(mf);
      if (dev.site_id) {
        const [siteData, screens, scheds, pls, media] = await Promise.all([
          api.get<Site>(`/api/sites/${dev.site_id}`).catch(() => null),
          api.get<Screen[]>(`/api/sites/${dev.site_id}/screens`).catch(() => [] as Screen[]),
          api.get<Schedule[]>(`/api/schedules?site_id=${dev.site_id}`).catch(() => [] as Schedule[]),
          api.get<Playlist[]>("/api/playlists").catch(() => [] as Playlist[]),
          api.get<Media[]>("/api/media").catch(() => [] as Media[]),
        ]);
        setSite(siteData as Site | null);
        setSchedules(scheds as Schedule[]);
        setPlaylists(pls as Playlist[]);
        setMediaList(media as Media[]);
        const sc = (screens as Screen[]).find((s) => s.id === dev.screen_id) ?? null;
        setScreen(sc);
        setLayoutDraft(sc?.layout ?? null);
      }
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [deviceId]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function saveLayout() {
    if (!screen) {
      setError("Device non rattaché à un écran.");
      return;
    }
    try {
      await api.patch(`/api/screens/${screen.id}`, { layout: layoutDraft });
      setNotice("Disposition enregistrée — publier pour l'inclure dans le manifeste.");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function publish() {
    try {
      await api.post(`/api/devices/${deviceId}/publish`);
      setNotice("Manifeste publié.");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  if (!device) {
    return <p className="text-sm text-muted-foreground">{error ?? "Chargement…"}</p>;
  }

  const shown = device.computed_status ?? device.status;
  // Conflits : plannings qui se chevauchent
  const conflicts: Array<[Schedule, Schedule]> = [];
  for (let i = 0; i < schedules.length; i++) {
    for (let j = i + 1; j < schedules.length; j++) {
      const a = schedules[i],
        b = schedules[j];
      if (!a.is_active || !b.is_active) continue;
      const as_ = new Date(a.start_at).getTime(),
        ae = new Date(a.end_at).getTime();
      const bs = new Date(b.start_at).getTime(),
        be = new Date(b.end_at).getTime();
      if (as_ < be && bs < ae) conflicts.push([a, b]);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/devices/${deviceId}`} className="text-sm text-muted-foreground hover:underline">
          ← Fiche device
        </Link>
        <h1 className="text-2xl font-bold">Disposition — {device.name}</h1>
        <p className="text-sm text-muted-foreground">
          <Badge variant={statusVariant(shown)}>{STATUS_LABEL[shown] ?? shown}</Badge>{" "}
          {site ? `Site : ${site.name}` : "—"} · Écran : {screen ? screen.name : "non rattaché"} · Manifeste :{" "}
          {adminStatus?.manifest_version != null ? `v${adminStatus.manifest_version}` : "—"}
        </p>
      </div>
      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {notice && <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</p>}

      {!screen && (
        <Card>
          <CardHeader>
            <CardTitle>Aucun écran rattaché</CardTitle>
            <CardDescription>
              Assignez ce device à un écran dans Sites & écrans pour configurer la disposition.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {screen && (
        <Card>
          <CardHeader>
            <CardTitle>Écran : {screen.name}</CardTitle>
            <CardDescription>
              {screen.width}×{screen.height} {screen.orientation} — disposition incluse dans le manifeste au prochain publish.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LayoutEditor
              value={layoutDraft}
              onChange={setLayoutDraft}
              mediaOptions={mediaList}
              playlistOptions={playlists}
            />
            <div className="mt-4 flex gap-2">
              <Button onClick={saveLayout}>Enregistrer la disposition</Button>
              <Button variant="outline" onClick={publish}>
                Publier le manifeste
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Planning du site</CardTitle>
          <CardDescription>
            Priorité la plus haute gagne ; à égalité, règle déterministe. Conflits signalés ci-dessous.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {schedules.length === 0 ? (
            <p className="text-sm text-muted-foreground">Aucun planning pour ce site.</p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nom</TableHead>
                    <TableHead>Playlist</TableHead>
                    <TableHead>Fenêtre</TableHead>
                    <TableHead>Prio</TableHead>
                    <TableHead>Actif</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...schedules]
                    .sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id))
                    .map((s) => (
                      <TableRow key={s.id}>
                        <TableCell className="font-medium">{s.name}</TableCell>
                        <TableCell>{playlists.find((p) => p.id === s.playlist_id)?.name ?? s.playlist_id}</TableCell>
                        <TableCell className="text-xs">
                          {formatDate(s.start_at)} → {formatDate(s.end_at)}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{s.priority}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={s.is_active ? "success" : "secondary"}>{s.is_active ? "actif" : "inactif"}</Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
              {conflicts.length > 0 && (
                <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
                  <div className="font-medium text-amber-900">Conflits détectés ({conflicts.length})</div>
                  <ul className="list-disc pl-5 text-amber-800">
                    {conflicts.map(([a, b]) => (
                      <li key={`${a.id}-${b.id}`}>
                        « {a.name} » (prio {a.priority}) ↔ « {b.name} » (prio {b.priority}) —{" "}
                        {a.priority !== b.priority
                          ? `« ${a.priority > b.priority ? a.name : b.name} » gagne.`
                          : "priorités égales — ordre déterministe par ID."}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {manifest && (
        <Card>
          <CardHeader>
            <CardTitle>Manifeste généré</CardTitle>
            <CardDescription>v{manifest.version} — le layout y figure si configuré.</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{manifest.payload.slice(0, 6000)}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
