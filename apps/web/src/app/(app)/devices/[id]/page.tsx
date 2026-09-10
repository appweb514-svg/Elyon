"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ApiError, api, formatBytes, formatDate } from "@/lib/api";
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
import { TvFrame } from "@/components/tv-frame";
import {
  LayoutEditor,
  type ScreenLayout,
} from "@/components/layout-editor";
import { useDragOrder } from "@/lib/use-drag-order";
import { WidgetBar, type Widget } from "@/components/widget-bar";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Copy,
  GripVertical,
  Loader2,
} from "lucide-react";

type Device = {
  id: string;
  name: string;
  serial: string;
  org_id?: string | null;
  status: string;
  computed_status?: string | null;
  site_id: string | null;
  screen_id: string | null;
  is_preview?: boolean;
  last_seen_at: string | null;
  player_state?: string | null;
  current_media_id?: string | null;
  uptime_seconds?: number | null;
  load_avg?: number | null;
  memory_percent?: number | null;
  cpu_percent?: number | null;
  storage_free_bytes?: number | null;
  lan_ip?: string | null;
  wifi_ssid?: string | null;
  network?: Record<string, unknown> | null;
  created_at: string;
};

type Site = { id: string; name: string };

type QueueItem = {
  media_id: string;
  name: string;
  kind: string;
  playing: boolean;
};

type WallFrame = {
  device_id: string;
  name: string;
  computed_status: string;
  player_state: string | null;
  current_media_id: string | null;
  current_media_name: string | null;
  current_media_kind: string | null;
  current_media_url?: string | null;
  current_page_index?: number | null;
  is_paused?: boolean;
  screen_width?: number | null;
  screen_height?: number | null;
  ticker_text?: string | null;
  ticker_speed?: string | null;
};

type Screen = {
  id: string;
  name: string;
  layout?: ScreenLayout | null;
  widgets?: Widget[] | null;
};

type Media = { id: string; name: string; kind: string; org_id?: string };
type Playlist = { id: string; name: string };
type PlaylistItem = {
  id: string;
  media_id: string;
  position: number;
  duration_seconds: number | null;
};
type PlaylistDetail = Playlist & { items: PlaylistItem[] };
type Command = { id: string; type: string; payload: string | null; status: string; created_at: string };
type Schedule = { id: string; playlist_id: string; name: string; start_at: string; end_at: string; priority: number; is_active: boolean; device_id?: string | null; excluded_for_this_device?: boolean };
type ManifestPreview = { version: number; payload: string; signature: string; published_at: string };

function formatUptime(totalSeconds: number): string {
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.floor((totalSeconds % 86400) / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  if (d > 0) return `${d} j ${h} h`;
  if (h > 0) return `${h} h ${m} min`;
  return `${m} min`;
}

function commandLabel(c: Command): string {
  let mediaName: string | null = null;
  if (c.payload) {
    try {
      const parsed = JSON.parse(c.payload) as { name?: string };
      mediaName = parsed.name ?? null;
    } catch {
      mediaName = null;
    }
  }
  if (c.type === "show") return mediaName ? `Afficher « ${mediaName} »` : "Afficher un média";
  if (c.type === "stop_show") return mediaName ? `Arrêter « ${mediaName} »` : "Arrêt de la diffusion";
  const labels: Record<string, string> = {
    resync: "Mise à jour du contenu",
    reboot: "Redémarrage",
    blank: "Écran éteint",
    unblank: "Écran rallumé",
    capture: "Capture d'écran",
  };
  return labels[c.type] ?? c.type;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente d'approbation",
  approved: "Prêt (éteint ou jamais connecté)",
  online: "En ligne",
  offline: "Hors ligne",
  syncing: "En cours de mise à jour",
  maintenance: "En maintenance",
  disabled: "Désactivé",
  blocked: "Bloqué",
};

const STATE_LABEL: Record<string, string> = {
  playing: "Diffuse un contenu",
  idle: "Écran en attente (aucun contenu programmé)",
  blank: "Écran volontairement éteint",
};

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "online") return "success";
  if (status === "pending" || status === "syncing") return "warning";
  if (status === "blocked" || status === "disabled") return "destructive";
  return "secondary";
}

export default function DeviceDetailPage() {
  const params = useParams<{ id: string }>();
  const deviceId = params.id;
  const [device, setDevice] = useState<Device | null>(null);
  const [wall, setWall] = useState<WallFrame | null>(null);
  const [commands, setCommands] = useState<Command[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [queueMediaId, setQueueMediaId] = useState("");
  const [assignPlaylist, setAssignPlaylist] = useState<string>("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedPlaylist, setExpandedPlaylist] = useState<PlaylistDetail | null>(null);
  const [mediaList, setMediaList] = useState<Media[]>([]);
  const [selectedMedia, setSelectedMedia] = useState("");
  const [itemDuration, setItemDuration] = useState("10");
  const [editingBusy, setEditingBusy] = useState(false);
  const [tab, setTab] = useState<"live" | "contenu" | "disposition" | "parametres">("live");
  const [sites, setSites] = useState<Site[]>([]);
  const [siteScreens, setSiteScreens] = useState<Screen[]>([]);
  const [genName, setGenName] = useState("");
  const [genSite, setGenSite] = useState("");
  const [genScreen, setGenScreen] = useState("");
  const [genPreview, setGenPreview] = useState(false);
  const [formInit, setFormInit] = useState(false);
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [netMode, setNetMode] = useState("dhcp");
  const [netIp, setNetIp] = useState("");
  const [netMask, setNetMask] = useState("24");
  const [netGw, setNetGw] = useState("");
  const [netDns1, setNetDns1] = useState("");
  const [netDns2, setNetDns2] = useState("");
  const [netHostname, setNetHostname] = useState("");
  const [savingNet, setSavingNet] = useState(false);
  const [layout, setLayout] = useState<ScreenLayout | null>(null);
  const [savingLayout, setSavingLayout] = useState(false);
  const [widgets, setWidgets] = useState<Widget[]>([]);
  const [savedWidgets, setSavedWidgets] = useState<Widget[]>([]);
  const [savingWidgets, setSavingWidgets] = useState(false);
  const [widgetOpenId, setWidgetOpenId] = useState<string | null>(null);
  // Gel du rechargement pendant l'édition (widgets OU disposition) : la ref
  // est lue à l'intérieur du callback, sans dépendre des closures du timer.
  const editingRef = useRef(false);
  useEffect(() => {
    editingRef.current = widgetOpenId !== null || savingLayout || savingWidgets;
  }, [widgetOpenId, savingLayout, savingWidgets]);
  const liveKey = useRef(0);

  const reload = useCallback(async () => {
    try {
      const dev = await api.get<Device>(`/api/devices/${deviceId}`);
      setDevice(dev);
      const [frame, cmds] = await Promise.all([
        api.get<WallFrame[]>("/api/admin/wall")
          .then((frames) => frames.find((f) => f.device_id === deviceId) ?? null)
          .catch(() => null),
        api.get<Command[]>(`/api/admin/devices/${deviceId}/commands`).catch(() => [] as Command[]),
      ]);
      setWall(frame);
      setCommands(cmds as Command[]);
      if (dev.screen_id) {
        const sites = await api.get<{ id: string }[]>("/api/sites").catch(() => []);
        for (const site of sites as { id: string }[]) {
          const screens = await api
            .get<Screen[]>(`/api/sites/${site.id}/screens`)
            .catch(() => [] as Screen[]);
          const found = (screens as Screen[]).find((s) => s.id === dev.screen_id);
          if (found) {
            if (!editingRef.current) {
              setLayout(found.layout ?? null);
              setWidgets((found.widgets ?? []) as Widget[]);
              setSavedWidgets((found.widgets ?? []) as Widget[]);
            }
            break;
          }
        }
      }
      if (dev.site_id) {
        const [scheds, pls] = await Promise.all([
          api.get<Schedule[]>(`/api/schedules?site_id=${dev.site_id}&device_id=${dev.id}`).catch(() => [] as Schedule[]),
          api.get<Playlist[]>("/api/playlists").catch(() => [] as Playlist[]),
        ]);
        if (!editingRef.current) {
          setSchedules(scheds as Schedule[]);
          setPlaylists(pls as Playlist[]);
        }
      }
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [deviceId]);

  useEffect(() => {
    reload();
    const timer = setInterval(() => {
      void reload();
    }, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId]);

  // Le flux MJPEG est reconnecté quand le média affiché change.
  const liveSrc = `/api/admin/wall/${deviceId}/live`;
  const currentMediaKey = wall?.current_media_id ?? "none";
  const screenRatio =
    wall?.screen_width && wall?.screen_height
      ? `${wall.screen_width} / ${wall.screen_height}`
      : undefined;
  const [liveBust, setLiveBust] = useState(0);
  useEffect(() => {
    liveKey.current += 1;
    setLiveBust((b) => b + 1);
  }, [currentMediaKey]);

  async function loadScreens(siteId: string) {
    if (!siteId) {
      setSiteScreens([]);
      return;
    }
    const list = await api.get<Screen[]>(`/api/sites/${siteId}/screens`).catch(() => [] as Screen[]);
    setSiteScreens(list as Screen[]);
  }

  useEffect(() => {
    api.get<Site[]>("/api/sites").then((list) => setSites(list as Site[])).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!device || formInit) return;
    setGenName(device.name);
    setGenSite(device.site_id ?? "");
    setGenScreen(device.screen_id ?? "");
    setGenPreview(Boolean(device.is_preview));
    const net = (device.network ?? {}) as Record<string, string>;
    setNetMode(String(net.mode ?? "dhcp"));
    setNetIp(String(net.ip ?? ""));
    setNetMask(String(net.netmask ?? "24"));
    setNetGw(String(net.gateway ?? ""));
    const dns = Array.isArray(net.dns) ? net.dns : [];
    setNetDns1(String(dns[0] ?? ""));
    setNetDns2(String(dns[1] ?? ""));
    setNetHostname(String(net.hostname ?? ""));
    setFormInit(true);
    if (device.site_id) void loadScreens(device.site_id);
  }, [device, formInit]);

  async function saveGeneral() {
    try {
      setSavingGeneral(true);
      await api.patch(`/api/devices/${deviceId}`, {
        name: genName.trim() || undefined,
        site_id: genSite || undefined,
        screen_id: genScreen || undefined,
        is_preview: genPreview,
      });
      setNotice("Paramètres enregistrés.");
      setFormInit(false);
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setSavingGeneral(false);
    }
  }

  async function saveNetwork() {
    try {
      setSavingNet(true);
      await api.post(`/api/devices/${deviceId}/network`, {
        mode: netMode,
        ip: netMode === "static" ? netIp.trim() : undefined,
        netmask: netMode === "static" ? netMask.trim() : undefined,
        gateway: netMode === "static" ? netGw.trim() : undefined,
        dns: [netDns1.trim(), netDns2.trim()].filter(Boolean),
        hostname: netHostname.trim() || undefined,
      });
      setNotice("Configuration réseau envoyée au Raspberry (commande NETWORK).");
      setFormInit(false);
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setSavingNet(false);
    }
  }

  const loadQueue = useCallback(async () => {
    try {
      const data = await api.get<{ items: QueueItem[] }>(`/api/devices/${deviceId}/queue`);
      setQueue(data.items ?? []);
    } catch {
      /* l'appareil peut ne pas être visible : on ignore */
    }
  }, [deviceId]);

  const refreshAll = useCallback(async () => {
    await loadQueue();
    await reload();
  }, [reload, loadQueue]);

  useEffect(() => {
    loadQueue();
    const h = setInterval(loadQueue, 4000);
    return () => clearInterval(h);
  }, [loadQueue]);

  useEffect(() => {
    api.get<Media[]>(`/api/media?device_id=${deviceId}`).then(setMediaList).catch(() => undefined);
  }, [deviceId]);

  async function queueAdd() {
    if (!queueMediaId) return;
    try {
      await api.post(`/api/devices/${deviceId}/queue`, { media_id: queueMediaId });
      setQueueMediaId("");
      setNotice("Média ajouté à la file.");
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function queuePlay(mediaId?: string) {
    try {
      await api.post(`/api/devices/${deviceId}/queue/play`, mediaId ? { media_id: mediaId } : {});
      setNotice("Lecture lancée.");
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function queueNext() {
    try {
      await api.post(`/api/devices/${deviceId}/queue/next`, {});
      setNotice("Média suivant lancé.");
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function togglePause() {
    const paused = wall?.is_paused === true || wall?.player_state === "paused";
    try {
      await api.post(`/api/devices/${deviceId}/commands`, {
        type: paused ? "resume" : "pause",
      });
      setNotice(paused ? "Diffusion reprise." : "Image figée (pause).");
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function queueStop() {
    try {
      await api.post(`/api/devices/${deviceId}/queue/stop`, {});
      setNotice("Diffusion arrêtée.");
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function queueRemove(mediaId: string) {
    try {
      await api.del(`/api/devices/${deviceId}/queue/${mediaId}`);
      await refreshAll();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function publish() {
    try {
      const mf = await api.post<ManifestPreview>(`/api/devices/${deviceId}/publish`);
      setNotice(`Contenu envoyé à l'écran (version ${mf.version}).`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  // Copie par-device : la playliste est dupliquée pour cet écran afin que ses
  // modifications (ajouts, retraits, ordre) ne concernent QUE cet appareil —
  // l'originale et les autres écrans restent intacts.
  async function forkPlaylistForDevice(sourceId: string): Promise<Playlist> {
    if (!device) throw new Error("Appareil inconnu");
    const source = await api.get<PlaylistDetail>(`/api/playlists/${sourceId}`);
    const baseName = `${source.name} · ${device.name}`;
    let name = baseName;
    let suffix = 2;
    let copy: Playlist | null = null;
    while (copy === null) {
      try {
        copy = await api.post<Playlist>("/api/playlists", { name });
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          name = `${baseName} (${suffix++})`;
          continue;
        }
        throw err;
      }
    }
    for (const item of source.items) {
      await api.post(`/api/playlists/${copy.id}/items`, {
        media_id: item.media_id,
        duration_seconds: item.duration_seconds ?? undefined,
      });
    }
    return copy;
  }

  async function assignPlaylistToScreen() {
    if (!assignPlaylist || !device?.site_id) {
      setError("Appareil sans site — rattachez-le d'abord à un site.");
      return;
    }
    try {
      const copy = await forkPlaylistForDevice(assignPlaylist);
      await api.post("/api/schedules", {
        site_id: device.site_id,
        playlist_id: copy.id,
        name: copy.name,
        start_at: new Date().toISOString(),
        end_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
        priority: 0,
        device_id: device.id,
      });
      setAssignPlaylist("");
      await publish();
      setNotice(
        "Copie de la playlist créée pour cet écran : personnalisez-la sans toucher à l'originale."
      );
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function toggleExpand(s: Schedule) {
    if (expandedId === s.id) {
      setExpandedId(null);
      setExpandedPlaylist(null);
      return;
    }
    if (!device) return;
    setEditingBusy(true);
    try {
      const [detail, media] = await Promise.all([
        api.get<PlaylistDetail>(`/api/playlists/${s.playlist_id}`),
        api.get<Media[]>(`/api/media?device_id=${deviceId}`),
      ]);
      setExpandedPlaylist(detail);
      setMediaList(media as Media[]);
      setExpandedId(s.id);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setEditingBusy(false);
    }
  }

  // Duplique une playlist partagée (« tous les écrans du site ») en copie
  // dédiée à cet écran, avec un planning ciblant l'appareil placé AU-DESSUS
  // de l'original : ici la copie prime, les autres écrans gardent l'originale.
  async function duplicateForDevice(s: Schedule) {
    if (!device?.site_id) return;
    setEditingBusy(true);
    try {
      const copy = await forkPlaylistForDevice(s.playlist_id);
      const created = await api.post<Schedule>("/api/schedules", {
        site_id: device.site_id,
        playlist_id: copy.id,
        name: copy.name,
        start_at: s.start_at,
        end_at: s.end_at,
        priority: s.priority,
        device_id: device.id,
      });
      const fresh = await api.get<Schedule[]>(`/api/schedules?site_id=${device.site_id}`);
      const siteOrder = [...(fresh as Schedule[])]
        .sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id))
        .map((x) => x.id);
      const idx = siteOrder.indexOf(s.id);
      siteOrder.splice(idx === -1 ? siteOrder.length : idx, 0, created.id);
      await api.post(`/api/sites/${device.site_id}/schedules/reorder`, siteOrder);
      const detail = await api.get<PlaylistDetail>(`/api/playlists/${copy.id}`);
      setExpandedPlaylist(detail);
      setExpandedId(created.id);
      setNotice(
        "Copie créée pour cet écran : elle prime sur l'original ici, les autres écrans conservent le contenu partagé."
      );
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setEditingBusy(false);
    }
  }

  async function addItemToExpanded() {
    if (!expandedPlaylist || !selectedMedia) return;
    setEditingBusy(true);
    try {
      const seconds = Number.parseInt(itemDuration, 10);
      const updated = await api.post<PlaylistDetail>(
        `/api/playlists/${expandedPlaylist.id}/items`,
        {
          media_id: selectedMedia,
          duration_seconds: Number.isNaN(seconds) || seconds < 1 ? null : seconds,
        }
      );
      setExpandedPlaylist(updated);
      setSelectedMedia("");
      await publish();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setEditingBusy(false);
    }
  }

  async function removeItemFromExpanded(item: PlaylistItem) {
    if (!expandedPlaylist) return;
    setEditingBusy(true);
    try {
      await api.del(`/api/playlists/${expandedPlaylist.id}/items/${item.id}`);
      const detail = await api.get<PlaylistDetail>(`/api/playlists/${expandedPlaylist.id}`);
      setExpandedPlaylist(detail);
      await publish();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setEditingBusy(false);
    }
  }

  async function moveItemInExpanded(item: PlaylistItem, direction: -1 | 1) {
    if (!expandedPlaylist) return;
    const ids = [...expandedPlaylist.items]
      .sort((a, b) => a.position - b.position)
      .map((i) => i.id);
    const index = ids.indexOf(item.id);
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    setEditingBusy(true);
    try {
      const updated = await api.post<PlaylistDetail>(
        `/api/playlists/${expandedPlaylist.id}/reorder`,
        ids
      );
      setExpandedPlaylist(updated);
      await publish();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setEditingBusy(false);
    }
  }

  async function saveLayout() {
    if (!device?.screen_id) return;
    setSavingLayout(true);
    try {
      await api.patch(`/api/screens/${device.screen_id}`, {
        layout: layout ?? { mode: "fullscreen", zones: [] },
      });
      await publish();
      setNotice("Disposition enregistrée et envoyée à l'écran.");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setSavingLayout(false);
    }
  }

  async function toggleSchedule(s: Schedule) {
    if (!device) return;
    const shared = !s.device_id;
    const hiddenHere = Boolean(s.excluded_for_this_device);
    try {
      if (shared) {
        // Planning partagé : on ne touche PAS à l'original (les autres écrans
        // le gardent) — on masque/réaffiche uniquement sur CET écran.
        if (hiddenHere) {
          await api.del(`/api/schedules/${s.id}/exclusions/${device.id}`);
          setNotice("Contenu réaffiché sur cet écran (les autres écrans n'ont pas bougé).");
        } else {
          await api.post(`/api/schedules/${s.id}/exclusions`, { device_id: device.id });
          setNotice("Contenu masqué sur cet écran uniquement — les autres écrans le diffusent toujours.");
        }
      } else {
        await api.patch(`/api/schedules/${s.id}`, { is_active: !s.is_active });
        setNotice(
          s.is_active
            ? "Contenu désactivé : il quitte l'écran au prochain cycle."
            : "Contenu réactivé et envoyé à l'écran."
        );
      }
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function removeSchedule(s: Schedule) {
    if (!device) return;
    if (!window.confirm("Supprimer définitivement cette programmation ?")) return;
    try {
      await api.del(`/api/schedules/${s.id}`);
      setNotice("Programmation supprimée et écrans mis à jour.");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  const widgetsChanged = JSON.stringify(widgets) !== JSON.stringify(savedWidgets);

  async function saveWidgets() {
    if (!device?.screen_id) return;
    setSavingWidgets(true);
    try {
      await api.patch(`/api/screens/${device.screen_id}`, {
        widgets: widgets.map((w) => ({
          type: w.type,
          position: w.position,
          visible: w.visible,
          params: w.params,
        })),
      });
      setSavedWidgets(widgets);
      setWidgetOpenId(null);
      await publish();
      setNotice("Widgets enregistrés et affichés sur l'écran.");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setSavingWidgets(false);
    }
  }

  // Seuls les contenus qui jouent réellement sur CET écran : programmations
  // ciblées sur l'appareil + programmations « tout le site » (device_id nul).
  const currentDeviceId = device?.id;
  const deviceSchedules = !currentDeviceId
    ? []
    : schedules.filter((s) => !s.device_id || s.device_id === currentDeviceId);
  const orderedSchedules = [...deviceSchedules]
    .sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));
  const sortedExpandedItems = expandedPlaylist
    ? [...expandedPlaylist.items].sort((a, b) => a.position - b.position)
    : [];
  const { itemProps, overId } = useDragOrder<Schedule>(
    orderedSchedules,
    (s) => s.id,
    (next) => {
      void (async () => {
        if (!device?.site_id) return;
        try {
          // L'API exige la liste COMPLÈTE des plannings du site : on réordonne
          // ceux affichés puis on rajoute les autres (autres écrans) dans leur
          // ordre courant.
          const hiddenIds = schedules
            .filter((s) => s.device_id && s.device_id !== device.id)
            .map((s) => s.id);
          const ids = [...next.map((s) => s.id), ...hiddenIds];
          await api.post<Schedule[]>(`/api/sites/${device.site_id}/schedules/reorder`, ids);
          setNotice("Priorités mises à jour et envoyées aux écrans.");
          await reload();
        } catch (err) {
          setError(String((err as Error).message ?? err));
        }
      })();
    }
  );

  const shown = device?.computed_status ?? device?.status ?? "";
  const isShowingDirect = wall?.player_state === "playing" && Boolean(wall?.current_media_id);
  const isPaused = wall?.is_paused === true || wall?.player_state === "paused";

  if (error && !device) {
    return (
      <div className="space-y-2">
        <Link href="/devices" className="text-sm text-muted-foreground hover:underline">← Appareils</Link>
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }
  if (!device) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/devices" className="text-sm text-muted-foreground hover:underline">← Appareils</Link>
          <h1 className="text-2xl font-bold">{device.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge variant={statusVariant(shown)}>{STATUS_LABEL[shown] ?? shown}</Badge>
            <span>{STATE_LABEL[wall?.player_state ?? ""] ?? "État inconnu"}</span>
            <span>· vu le {formatDate(device.last_seen_at)}</span>
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" onClick={async () => {
            try {
              await api.post(`/api/devices/${deviceId}/commands`, { type: "resync" });
              setNotice("Mise à jour forcée envoyée.");
              await reload();
            } catch (err) {
              setError(String((err as Error).message ?? err));
            }
          }}>
            Forcer la mise à jour
          </Button>
          <Button onClick={publish}>Envoyer le contenu</Button>
        </div>
      </div>

      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {notice && <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</p>}

      <div className="flex flex-wrap gap-2 border-b pb-2">
        {(
          [
            ["live", "Aperçu en direct"],
            ["contenu", "Contenu & priorités"],
            ["disposition", "Disposition de l'écran"],
            ["parametres", "Paramètres"],
          ] as const
        ).map(([key, label]) => (
          <Button key={key} variant={tab === key ? "default" : "ghost"} size="sm" onClick={() => setTab(key)}>
            {label}
          </Button>
        ))}
      </div>

      {tab === "live" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Ce que l&apos;écran affiche maintenant</CardTitle>
              <CardDescription>
                Image en direct (flux vidéo continu, sans rechargement).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <TvFrame
                label={wall?.computed_status === "online" ? "live" : "off"}
                ratio={screenRatio}
              >
                {/* Flux MJPEG : le navigateur met à jour l'image tout seul,
                    comme un vrai retour vidéo. La clé force la reconnexion
                    quand le média affiché change. */}
                {wall?.player_state !== "playing" && wall?.player_state !== "blank" ? (
                  <div className="elyon-idle absolute inset-0 flex flex-col items-center justify-center gap-3 overflow-hidden">
                    <span className="elyon-idle-orb left-[8%] top-[15%] h-24 w-24 bg-sky-500" />
                    <span className="elyon-idle-orb right-[10%] top-[55%] h-32 w-32 bg-indigo-500" style={{ animationDelay: "3s" }} />
                    <span className="elyon-idle-orb bottom-[10%] left-[45%] h-20 w-20 bg-cyan-400" style={{ animationDelay: "6s" }} />
                    <span className="elyon-idle-text text-lg font-semibold tracking-wide text-slate-100">
                      Affichage en préparation
                    </span>
                    {wall?.ticker_text ? (
                      <div className="absolute bottom-0 left-0 right-0 overflow-hidden bg-black/70 px-3 py-1.5 text-xs whitespace-nowrap text-slate-100">
                        <span className={`elyon-ticker inline-block ${wall.ticker_speed && wall.ticker_speed !== "normal" ? `elyon-ticker-${wall.ticker_speed}` : ""}`}>
                          {wall.ticker_text}
                        </span>
                      </div>
                    ) : null}
                  </div>
                ) : wall?.current_media_kind === "web" && wall?.current_media_url ? (
                  <iframe
                    key={currentMediaKey}
                    src={wall.current_media_url}
                    title={wall.current_media_name ?? "page web"}
                    className="h-full w-full border-0 bg-white"
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-presentation"
                  />
                ) : (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    key={liveBust}
                    src={liveSrc}
                    alt={wall?.current_media_name ?? "aperçu écran"}
                    className="h-full w-full object-contain"
                  />
                )}
              </TvFrame>
              <div className="mx-auto mt-4 w-full max-w-3xl space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    File de diffusion
                    {isPaused && <Badge variant="warning">En pause</Badge>}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => queuePlay()} disabled={queue.length === 0}>
                      ▶ Reprendre
                    </Button>
                    <Button
                      size="sm"
                      variant={isPaused ? "default" : "outline"}
                      onClick={() => void togglePause()}
                      disabled={!isShowingDirect && !isPaused}
                      title={isPaused ? "Reprendre la diffusion" : "Figer l'image affichée"}
                    >
                      {isPaused ? "▶ Reprendre" : "⏸ Pause"}
                    </Button>
                    <Button size="sm" variant="outline" onClick={queueNext} disabled={queue.length < 2}>
                      ⏭ Suivant
                    </Button>
                    <Button size="sm" variant="destructive" onClick={queueStop} disabled={!isShowingDirect}>
                      ⏹ Arrêter la diffusion
                    </Button>
                  </div>
                </div>
                {queue.length === 0 ? (
                  <p className="rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
                    Aucun média dans la file. Ajoutez des médias ci-dessous : le premier lu
                    restera à l&apos;écran jusqu&apos;au suivant ou à l&apos;arrêt.
                  </p>
                ) : (
                  <div className="overflow-hidden rounded-lg border">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                          <th className="px-3 py-2">#</th>
                          <th className="px-3 py-2">Média</th>
                          <th className="px-3 py-2">Type</th>
                          <th className="px-3 py-2">État</th>
                          <th className="px-3 py-2 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {queue.map((item, i) => (
                          <tr key={item.media_id} className="border-b last:border-0">
                            <td className="px-3 py-2 text-xs text-muted-foreground">{i + 1}</td>
                            <td className="max-w-[220px] truncate px-3 py-2 font-medium">{item.name}</td>
                            <td className="px-3 py-2 text-xs text-muted-foreground">{item.kind}</td>
                            <td className="px-3 py-2">
                              {item.playing ? (
                                <Badge variant="success">En lecture</Badge>
                              ) : (
                                <Badge variant="secondary">En attente</Badge>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              <div className="flex justify-end gap-1">
                                {!item.playing && (
                                  <Button size="sm" variant="ghost" onClick={() => queuePlay(item.media_id)} title="Lire ce média">
                                    ▶
                                  </Button>
                                )}
                                <Button size="sm" variant="ghost" onClick={() => queueRemove(item.media_id)} title="Retirer de la file">
                                  ✕
                                </Button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    className="max-w-xs"
                    value={queueMediaId}
                    onChange={(e) => setQueueMediaId(e.target.value)}
                  >
                    <option value="">Ajouter un média à la file…</option>
                    {mediaList
                      .filter((m) => !device?.org_id || m.org_id === device.org_id)
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                  </Select>
                  <Button size="sm" onClick={queueAdd} disabled={!queueMediaId}>
                    Ajouter
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Santé de l&apos;appareil</CardTitle>
                <CardDescription>
                  Métriques rapportées par le player à chaque battement de cœur.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {device.uptime_seconds == null &&
                device.memory_percent == null &&
                device.cpu_percent == null &&
                device.lan_ip == null ? (
                  <p className="text-sm text-muted-foreground">
                    Aucune télémétrie reçue pour l&apos;instant — elle apparaîtra après le
                    prochain battement de cœur.
                  </p>
                ) : (
                  <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                    {device.uptime_seconds != null && (
                      <div>
                        <dt className="text-xs text-muted-foreground">Uptime</dt>
                        <dd className="font-medium">{formatUptime(device.uptime_seconds)}</dd>
                      </div>
                    )}
                    {device.cpu_percent != null && (
                      <div>
                        <dt className="text-xs text-muted-foreground">CPU</dt>
                        <dd className="font-medium">{Math.round(device.cpu_percent)} %</dd>
                      </div>
                    )}
                    {device.memory_percent != null && (
                      <div>
                        <dt className="text-xs text-muted-foreground">Mémoire</dt>
                        <dd className="font-medium">{Math.round(device.memory_percent)} %</dd>
                      </div>
                    )}
                    {device.load_avg != null && (
                      <div>
                        <dt className="text-xs text-muted-foreground">Charge</dt>
                        <dd className="font-medium">{device.load_avg.toFixed(2)}</dd>
                      </div>
                    )}
                    {device.storage_free_bytes != null && (
                      <div>
                        <dt className="text-xs text-muted-foreground">Stockage libre</dt>
                        <dd className="font-medium">{formatBytes(device.storage_free_bytes)}</dd>
                      </div>
                    )}
                    {device.lan_ip && (
                      <div>
                        <dt className="text-xs text-muted-foreground">Adresse LAN</dt>
                        <dd className="font-mono text-xs">{device.lan_ip}</dd>
                      </div>
                    )}
                    {device.wifi_ssid && (
                      <div>
                        <dt className="text-xs text-muted-foreground">Réseau Wi-Fi</dt>
                        <dd className="font-medium">{device.wifi_ssid}</dd>
                      </div>
                    )}
                  </dl>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Widgets d&apos;information</CardTitle>
                <CardDescription>
                  Météo, flux RSS ou texte libre, affichés en bas de l&apos;écran.
                  L&apos;œil cache ou affiche le widget, l&apos;icône de réglage définit
                  son emplacement et ses paramètres.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <WidgetBar widgets={widgets} onChange={setWidgets} openId={widgetOpenId} onOpenChange={setWidgetOpenId} />
                {widgetsChanged && (
                  <Button className="mt-3 w-full" onClick={saveWidgets} disabled={savingWidgets || !device.screen_id}>
                    {savingWidgets ? "Envoi…" : "Enregistrer et afficher sur l'écran"}
                  </Button>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Dernières actions</CardTitle>
                <CardDescription>Commandes envoyées à cet appareil.</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {commands.slice(0, 6).map((c) => (
                    <li key={c.id} className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate">{commandLabel(c)}</p>
                        <p className="text-xs text-muted-foreground">{formatDate(c.created_at)}</p>
                      </div>
                      {c.status === "acked" ? null : c.status === "failed" ? (
                        <Badge variant="destructive">échec</Badge>
                      ) : (
                        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" aria-label="En cours" />
                      )}
                    </li>
                  ))}
                  {commands.length === 0 && <li className="text-muted-foreground">Aucune action pour l&apos;instant.</li>}
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {tab === "contenu" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Contenus affichés sur cet écran</CardTitle>
              <CardDescription>
                Glissez-déposez pour changer la priorité : le premier de la liste gagne quand
                plusieurs contenus sont programmés en même temps.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {orderedSchedules.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aucun contenu programmé.</p>
              ) : (
                <ul className="space-y-2">
                  {orderedSchedules.map((s, index) => (
                    <li
                      key={s.id}
                      {...itemProps(s.id)}
                      className={
                        "rounded-md border transition-colors" +
                        (overId === s.id ? " border-primary bg-primary/5" : "") +
                        (s.excluded_for_this_device || !s.is_active ? " opacity-60" : "")
                      }
                    >
                      <div className="flex flex-wrap cursor-grab items-center gap-3 p-3 active:cursor-grabbing">
                        <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1 basis-[calc(100%-4rem)] sm:basis-auto">
                          <p className="truncate text-sm font-medium">
                            {playlists.find((p) => p.id === s.playlist_id)?.name ?? s.name}
                          </p>
                          <p className="truncate text-xs text-muted-foreground">
                            {formatDate(s.start_at)} → {formatDate(s.end_at)}
                            {!s.device_id && (
                              <span className="ml-1 text-amber-600 dark:text-amber-400">
                                · tous les écrans du site
                              </span>
                            )}
                          </p>
                          <Link
                            href={`/playlists/${s.playlist_id}`}
                            className="text-xs text-primary hover:underline"
                          >
                            Ouvrir dans Playlists
                          </Link>
                        </div>
                        <Badge
                          variant={
                            s.excluded_for_this_device
                              ? "secondary"
                              : s.is_active
                                ? "success"
                                : "secondary"
                          }
                        >
                          {s.excluded_for_this_device
                            ? "masqué ici"
                            : s.is_active
                              ? "actif"
                              : "inactif"}
                        </Badge>
                        <Button
                          className="w-full sm:w-auto"
                          size="sm"
                          variant={expandedId === s.id ? "default" : "outline"}
                          onClick={() => toggleExpand(s)}
                          disabled={editingBusy}
                           title={
                             s.device_id
                               ? "Réglages de la playlist pour cet écran"
                               : "Consulter la playlist de base en lecture seule"
                           }
                         >
                           {expandedId === s.id ? <ChevronDown /> : <ChevronRight />} {s.device_id ? "Réglages" : "Consulter"}

                        </Button>
                        <Button
                          className="w-full sm:w-auto"
                          size="sm"
                          variant="outline"
                          onClick={() => toggleSchedule(s)}
                          title={
                            !s.device_id
                              ? s.excluded_for_this_device
                                ? "Réafficher ce contenu sur cet écran (sans toucher aux autres)"
                                : "Masquer ce contenu sur cet écran uniquement (les autres écrans le gardent)"
                              : s.is_active
                                ? "Suspendre ce contenu (il quitte l'écran)"
                                : "Réactiver ce contenu"
                          }
                        >
                          {!s.device_id
                            ? s.excluded_for_this_device
                              ? "Afficher ici"
                              : "Masquer ici"
                            : s.is_active
                              ? "Désactiver"
                              : "Activer"}
                        </Button>
                        <Button
                          className="w-full sm:w-auto"
                          size="sm"
                          variant="destructive"
                          onClick={() => removeSchedule(s)}
                          title="Supprimer définitivement cette programmation"
                        >
                          Supprimer
                        </Button>
                      </div>
                      {expandedId === s.id && expandedPlaylist && (
                         <div className="min-w-0 space-y-3 border-t bg-muted/30 p-3">

                           {!s.device_id && (
                             <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                               <span>
                                 Cette playlist de base est partagée avec tous les appareils du site et
                                 ne peut pas être modifiée ici. Dupliquez-la pour personnaliser son
                                 contenu uniquement sur cet appareil.
                               </span>
                               <Button
                                 size="sm"
                                 variant="outline"
                                 onClick={() => duplicateForDevice(s)}
                                 disabled={editingBusy}
                               >
                                 <Copy /> Dupliquer pour cet appareil
                               </Button>
                             </div>
                           )}

                           <p className="text-xs font-medium">
                             Séquence ({sortedExpandedItems.length})
                             {s.device_id
                               ? " — chaque modification est envoyée immédiatement à cet appareil."
                               : " — lecture seule ; dupliquez la playlist pour la personnaliser."}
                           </p>

                          <ul className="space-y-1">
                            {sortedExpandedItems.map((item, itemIndex) => {
                              const media = mediaList.find((m) => m.id === item.media_id);
                              return (
                                 <li
                                   key={item.id}
                                   className="flex flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-sm"
                                 >

                                  <span className="w-5 shrink-0 text-right text-xs text-muted-foreground">
                                    {itemIndex + 1}
                                  </span>
                                  <div className="min-w-0 flex-1">
                                    <p className="truncate">{media?.name ?? item.media_id}</p>
                                    <p className="text-xs text-muted-foreground">
                                      {media?.kind ?? "—"} ·{" "}
                                      {item.duration_seconds
                                        ? `${item.duration_seconds} s`
                                        : "fin de lecture"}
                                    </p>
                                  </div>
                                     <Button
                                       className="shrink-0"
                                       size="icon"
                                       variant="ghost"

                                     disabled={!s.device_id || itemIndex === 0 || editingBusy}
                                     onClick={() => moveItemInExpanded(item, -1)}
                                     aria-label="Monter dans la séquence"

                                  >
                                    <ArrowUp />
                                  </Button>
                                     <Button
                                       className="shrink-0"
                                       size="icon"
                                       variant="ghost"

                                     disabled={!s.device_id || itemIndex === sortedExpandedItems.length - 1 || editingBusy}
                                     onClick={() => moveItemInExpanded(item, 1)}
                                     aria-label="Descendre dans la séquence"

                                  >
                                    <ArrowDown />
                                  </Button>
                                   <Button
                                     size="sm"
                                     variant="destructive"
                                     disabled={!s.device_id || editingBusy}
                                     onClick={() => removeItemFromExpanded(item)}

                                  >
                                    Retirer
                                  </Button>
                                </li>
                              );
                            })}
                            {sortedExpandedItems.length === 0 && (
                              <li className="text-sm text-muted-foreground">
                                Playlist vide — ajoutez un média ci-dessous.
                              </li>
                            )}
                          </ul>
                          <div className="flex flex-wrap items-end gap-2">
                            <div className="min-w-48 flex-1 space-y-1">
                              <Label htmlFor={`item-media-${expandedPlaylist.id}`}>
                                Ajouter un média
                              </Label>
                               <Select
                                 id={`item-media-${expandedPlaylist.id}`}
                                 value={selectedMedia}
                                 onChange={(e) => setSelectedMedia(e.target.value)}
                                 disabled={!s.device_id}
                               >

                                <option value="">— Choisir un média —</option>
                                {mediaList.map((m) => (
                                  <option key={m.id} value={m.id}>
                                    {m.name} ({m.kind})
                                  </option>
                                ))}
                              </Select>
                            </div>
                            <div className="w-24 space-y-1">
                              <Label htmlFor={`item-duration-${expandedPlaylist.id}`}>
                                Durée (s)
                              </Label>
                              <Input
                                id={`item-duration-${expandedPlaylist.id}`}
                                type="number"
                                min={1}
                                value={itemDuration}
                               onChange={(e) => setItemDuration(e.target.value)}
                               disabled={!s.device_id}
                             />

                            </div>
                             <Button
                               onClick={addItemToExpanded}
                               disabled={!s.device_id || !selectedMedia || editingBusy}

                            >
                              {editingBusy ? <Loader2 className="animate-spin" /> : "Ajouter"}
                            </Button>
                          </div>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <div className="space-y-2 rounded-md border p-3">
                <Label htmlFor="assign-playlist">Ajouter une playlist sur cet écran</Label>
                <div className="flex flex-wrap gap-2">
                  <Select id="assign-playlist" value={assignPlaylist} onChange={(e) => setAssignPlaylist(e.target.value)} className="min-w-56 flex-1">
                    <option value="">— Choisir une playlist —</option>
                    {playlists.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </Select>
                  <Button onClick={assignPlaylistToScreen} disabled={!assignPlaylist}>Affecter et envoyer</Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Une copie de la playlist est créée pour cet écran (30 jours). Personnalisez-la
                  ensuite (ajouts, retraits, ordre) via le bouton « Réglages » de la liste
                  ci-dessus — sans toucher à l&apos;originale ni aux autres appareils.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {tab === "disposition" && (
        <Card>
          <CardHeader>
            <CardTitle>Disposition de l&apos;écran</CardTitle>
            <CardDescription>
              Comment le contenu occupe l&apos;écran : plein écran, bandeau + vidéo, grille…
              Les changements sont envoyés directement à cet écran.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!device.screen_id ? (
              <p className="text-sm text-muted-foreground">
                Cet appareil n&apos;est rattaché à aucun écran. Rattachez-le depuis
                « Sites & écrans » pour personnaliser sa disposition.
              </p>
            ) : (
              <>
                <LayoutEditor
                  value={layout}
                  onChange={setLayout}
                  mediaOptions={[]}
                  playlistOptions={playlists}
                />
                <div className="flex gap-2">
                  <Button onClick={saveLayout} disabled={savingLayout || !layout}>
                    {savingLayout ? "Envoi…" : "Enregistrer et envoyer"}
                  </Button>
                  {layout && (
                    <Button variant="outline" onClick={() => setLayout(null)}>
                      Revenir au plein écran par défaut
                    </Button>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {tab === "parametres" && device && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Général</CardTitle>
              <CardDescription>Nom, site, écran rattaché et aperçu administrateur.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1">
                <Label>Nom de l&apos;appareil</Label>
                <Input value={genName} onChange={(e) => setGenName(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Site</Label>
                <Select value={genSite} onChange={(e) => { setGenSite(e.target.value); loadScreens(e.target.value); }}>
                  <option value="">— Aucun —</option>
                  {sites.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Écran rattaché</Label>
                <Select value={genScreen} onChange={(e) => setGenScreen(e.target.value)}>
                  <option value="">— Aucun —</option>
                  {siteScreens.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </Select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={genPreview}
                  onChange={(e) => setGenPreview(e.target.checked)}
                />
                Aperçu administrateur (brouillon non publié)
              </label>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Série : <code>{device.serial}</code></span>
                <span>· Statut : {device.status}</span>
              </div>
              <Button onClick={saveGeneral} disabled={savingGeneral}>
                {savingGeneral ? "Enregistrement…" : "Enregistrer"}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Réseau</CardTitle>
              <CardDescription>
                IP, passerelle, DNS et nom d&apos;hôte appliqués par l&apos;agent sur le
                Raspberry. Sur les players émulés, la commande est ignorée (réseau du conteneur).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
                IP remontée : <strong>{device.lan_ip ?? "—"}</strong>
                {device.wifi_ssid ? <> · Wi-Fi : <strong>{device.wifi_ssid}</strong></> : null}
              </div>
              <div className="space-y-1">
                <Label>Mode</Label>
                <Select value={netMode} onChange={(e) => setNetMode(e.target.value)}>
                  <option value="dhcp">DHCP (automatique)</option>
                  <option value="static">IP statique</option>
                </Select>
              </div>
              {netMode === "static" && (
                <>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label>Adresse IP (ou CIDR)</Label>
                      <Input value={netIp} onChange={(e) => setNetIp(e.target.value)} placeholder="192.168.1.50 ou 192.168.1.50/24" />
                    </div>
                    <div className="space-y-1">
                      <Label>Masque (ou préfixe)</Label>
                      <Input value={netMask} onChange={(e) => setNetMask(e.target.value)} placeholder="255.255.255.0 ou 24" />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label>Passerelle</Label>
                    <Input value={netGw} onChange={(e) => setNetGw(e.target.value)} placeholder="192.168.1.1" />
                  </div>
                </>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label>DNS primaire</Label>
                  <Input value={netDns1} onChange={(e) => setNetDns1(e.target.value)} placeholder="1.1.1.1" />
                </div>
                <div className="space-y-1">
                  <Label>DNS secondaire</Label>
                  <Input value={netDns2} onChange={(e) => setNetDns2(e.target.value)} placeholder="8.8.8.8" />
                </div>
              </div>
              <div className="space-y-1">
                <Label>Nom d&apos;hôte</Label>
                <Input value={netHostname} onChange={(e) => setNetHostname(e.target.value)} placeholder="elyon-salon" />
              </div>
              <Button onClick={saveNetwork} disabled={savingNet}>
                {savingNet ? "Envoi…" : "Appliquer au Raspberry"}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
