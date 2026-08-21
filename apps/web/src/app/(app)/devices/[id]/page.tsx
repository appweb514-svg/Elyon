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

type HeartbeatAdmin = {
  status: string;
  last_seen_at: string | null;
  device_status: string;
};

type ManifestPreview = {
  version: number;
  payload: string;
  signature: string;
  published_at: string;
};

type Command = {
  id: string;
  type: string;
  payload: string | null;
  status: string;
  created_at: string;
};

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
type MediaItem = { id: string; name: string; kind: string };

const COMMAND_TYPES = ["reboot", "resync", "blank", "unblank", "capture"] as const;

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

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "online" || status === "approved") return "success";
  if (status === "pending" || status === "syncing") return "warning";
  if (status === "blocked" || status === "disabled") return "destructive";
  if (status === "maintenance") return "secondary";
  if (status === "offline") return "secondary";
  return "secondary";
}

function parseManifest(
  preview: ManifestPreview | null
): { blocks: unknown[]; media: unknown[]; published_at: string | null } | null {
  if (!preview) return null;
  try {
    const payload = JSON.parse(preview.payload) as Record<string, unknown>;
    return {
      blocks: (payload.blocks as unknown[]) ?? [],
      media: (payload.media as unknown[]) ?? [],
      published_at: (payload.published_at as string) ?? preview.published_at,
    };
  } catch {
    return null;
  }
}

export default function DeviceDetailPage() {
  const params = useParams<{ id: string }>();
  const deviceId = params.id;
  const [device, setDevice] = useState<Device | null>(null);
  const [adminStatus, setAdminStatus] = useState<AdminStatus | null>(null);
  const [heartbeat, setHeartbeat] = useState<HeartbeatAdmin | null>(null);
  const [commands, setCommands] = useState<Command[]>([]);
  const [manifest, setManifest] = useState<ManifestPreview | null>(null);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [mediaById, setMediaById] = useState<Record<string, MediaItem>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [commandType, setCommandType] = useState<string>("resync");
  const [assignPlaylist, setAssignPlaylist] = useState<string>("");
  const [tab, setTab] = useState<"supervision" | "contenu" | "planning">("supervision");

  const reload = useCallback(async () => {
    try {
      const dev = await api.get<Device>(`/api/devices/${deviceId}`);
      setDevice(dev);
      // Endpoints admin — accessibles à l'utilisateur (pas au device Bearer)
      const [status, hb, cmds, mf] = await Promise.all([
        api.get<AdminStatus>(`/api/admin/devices/${deviceId}/status`).catch(() => null),
        api.get<HeartbeatAdmin>(`/api/admin/devices/${deviceId}/heartbeat`).catch(() => null),
        api.get<Command[]>(`/api/admin/devices/${deviceId}/commands`).catch(() => [] as Command[]),
        api.get<ManifestPreview>(`/api/admin/devices/${deviceId}/manifest`).catch(() => null),
      ]);
      setAdminStatus(status);
      setHeartbeat(hb);
      setCommands(cmds as Command[]);
      setManifest(mf);
      // Contenu/Planning du device (site)
      if (dev.site_id) {
        const [scheds, pls] = await Promise.all([
          api.get<Schedule[]>(`/api/schedules?site_id=${dev.site_id}`).catch(() => [] as Schedule[]),
          api.get<Playlist[]>("/api/playlists").catch(() => [] as Playlist[]),
        ]);
        setSchedules(scheds as Schedule[]);
        setPlaylists(pls as Playlist[]);
        const media = await api.get<MediaItem[]>("/api/media").catch(() => [] as MediaItem[]);
        const byId: Record<string, MediaItem> = {};
        for (const m of media as MediaItem[]) byId[m.id] = m;
        setMediaById(byId);
      }
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [deviceId]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function sendCommand() {
    try {
      await api.post(`/api/devices/${deviceId}/commands`, { type: commandType });
      setNotice(`Commande « ${commandType} » envoyée.`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function publish() {
    try {
      const mf = await api.post<ManifestPreview>(`/api/devices/${deviceId}/publish`);
      setNotice(`Publication effectuée (version ${mf.version}).`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function resync() {
    try {
      await api.post(`/api/devices/${deviceId}/commands`, { type: "resync" });
      const mf = await api.post<ManifestPreview>(`/api/devices/${deviceId}/publish`);
      setNotice(`Re-synchronisation : commande resync + manifeste v${mf.version}.`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function assignPlaylistToScreen() {
    if (!assignPlaylist || !device?.screen_id) {
      setError("Device non rattaché à un écran — créer/assigner d'abord.");
      return;
    }
    // La programmation se fait via un planning : on crée un planning qui lie playlist + site.
    if (!device.site_id) {
      setError("Device sans site.");
      return;
    }
    try {
      await api.post("/api/schedules", {
        site_id: device.site_id,
        playlist_id: assignPlaylist,
        name: `Programmation ${playlists.find((p) => p.id === assignPlaylist)?.name ?? assignPlaylist}`,
        start_at: new Date().toISOString(),
        end_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
        priority: 0,
      });
      setNotice("Playlist affectée (planning créé). Publier pour générer le manifeste.");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  if (error && !device) {
    return (
      <div className="space-y-2">
        <Link href="/devices" className="text-sm text-muted-foreground hover:underline">
          ← Appareils
        </Link>
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }
  if (!device) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }

  const shown = device.computed_status ?? device.status;
  const parsedManifest = parseManifest(manifest);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link href="/devices" className="text-sm text-muted-foreground hover:underline">
            ← Appareils
          </Link>
          <h1 className="text-2xl font-bold">{device.name}</h1>
          <p className="text-sm text-muted-foreground">
            Série {device.serial} · <Badge variant={statusVariant(shown)}>{STATUS_LABEL[shown] ?? shown}</Badge>{" "}
            {adminStatus?.manifest_version != null && (
              <span className="ml-2 text-xs">manifeste v{adminStatus.manifest_version}</span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={resync}>
            Re-synchroniser
          </Button>
          <Button onClick={publish}>Publier maintenant</Button>
        </div>
      </div>

      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {notice && <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</p>}

      <div className="flex gap-2 border-b pb-2">
        {(
          [
            ["supervision", "Supervision"],
            ["contenu", "Contenu diffusé"],
            ["planning", "Planning"],
          ] as const
        ).map(([key, label]) => (
          <Button
            key={key}
            variant={tab === key ? "default" : "ghost"}
            size="sm"
            onClick={() => setTab(key)}
          >
            {label}
          </Button>
        ))}
      </div>

      {tab === "supervision" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>État</CardTitle>
              <CardDescription>Dernier contact : {formatDate(device.last_seen_at)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <p>
                Statut calculé : <strong>{adminStatus?.computed_status ?? shown}</strong>
              </p>
              <p>
                Statut brut : <strong>{device.status}</strong>
              </p>
              <p>
                Dernier heartbeat : <strong>{heartbeat?.last_seen_at ? formatDate(heartbeat.last_seen_at) : "—"}</strong>
              </p>
              <p>
                Écran : <strong>{device.screen_id ?? "—"}</strong>
              </p>
              <p>
                Version manifeste : <strong>{adminStatus?.manifest_version ?? "—"}</strong>
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Envoyer une commande</CardTitle>
              <CardDescription>reboot, resync, blank/unblank, capture.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="command-type">Type</Label>
                <Select
                  id="command-type"
                  value={commandType}
                  onChange={(e) => setCommandType(e.target.value)}
                >
                  {COMMAND_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </Select>
              </div>
              <Button onClick={sendCommand}>Envoyer</Button>
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>Historique des commandes</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Horodatage</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Statut</TableHead>
                    <TableHead>Payload</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {commands.map((command) => (
                    <TableRow key={command.id}>
                      <TableCell className="whitespace-nowrap">{formatDate(command.created_at)}</TableCell>
                      <TableCell>{command.type}</TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            command.status === "acked"
                              ? "success"
                              : command.status === "error" || command.status === "failed"
                                ? "destructive"
                                : "secondary"
                          }
                        >
                          {command.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-48 truncate">{command.payload ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                  {commands.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={4} className="text-muted-foreground">
                        Aucune commande envoyée.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {tab === "contenu" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Programmation active</CardTitle>
              <CardDescription>
                Manifeste {manifest ? `v${manifest.version} — ${formatDate(manifest.published_at)}` : "aucun publié"} · média en cours : supervision/heartbeat
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {!parsedManifest || parsedManifest.blocks.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aucun bloc programmé — créer un planning puis publier.</p>
              ) : (
                <div className="space-y-2">
                  {parsedManifest.blocks.map((block: unknown, idx: number) => {
                    const b = block as Record<string, unknown>;
                    const entries = (b.entries as unknown[]) ?? [];
                    return (
                      <div key={String(b.schedule_id ?? idx)} className="rounded-md border p-3">
                        <div className="text-sm font-medium">
                          {String(b.schedule_name ?? b.schedule_id)} — prio {String(b.priority)}
                        </div>
                        <ul className="mt-1 list-disc pl-5 text-sm">
                          {(entries as unknown[]).map((e: unknown) => {
                            const ent = e as Record<string, unknown>;
                            const mid = String(ent.media_id ?? "");
                            const media = mediaById[mid];
                            return (
                              <li key={mid}>
                                {media ? `${media.name} (${media.kind})` : mid} — {String(ent.duration_seconds ?? "—")} s
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    );
                  })}
                  <div className="text-xs text-muted-foreground">Médias du manifeste : {parsedManifest.media.length} fichier(s) référencé(s).</div>
                </div>
              )}
              <div className="flex gap-2">
                <Select value={assignPlaylist} onChange={(e) => setAssignPlaylist(e.target.value)}>
                  <option value="">— Choisir une playlist à affecter —</option>
                  {playlists.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                <Button onClick={assignPlaylistToScreen} disabled={!assignPlaylist}>
                  Affecter
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                L&apos;affectation crée un planning (priorité 0, 30 jours) pour le site du device. Publier ensuite.
              </p>
            </CardContent>
          </Card>
          {manifest && (
            <Card>
              <CardHeader>
                <CardTitle>Manifeste brut</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{manifest.payload.slice(0, 4000)}</pre>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {tab === "planning" && (
        <Card>
          <CardHeader>
            <CardTitle>Planning du device (site)</CardTitle>
            <CardDescription>
              Jours/heures, fuseau, priorité, validité. Priorité la plus haute gagne ; à égalité, l&apos;ID le plus petit l&apos;emporte.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {schedules.length === 0 ? (
              <p className="text-sm text-muted-foreground">Aucun planning pour ce site.</p>
            ) : (
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
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              Gérer les plannings depuis <Link href="/schedules" className="underline">Plannings</Link>. Les conflits sont signalés à la création (priorité la plus élevée l&apos;emporte).
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
