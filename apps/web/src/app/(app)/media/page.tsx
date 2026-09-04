"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Eye, FolderInput, ListPlus, Pencil, Share2, Trash2 } from "lucide-react";

import { api, formatBytes, formatDate } from "@/lib/api";
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Media = {
  id: string;
  name: string;
  original_filename: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  team_name?: string | null;
  pages_count?: number | null;
  deleted_at: string | null;
  created_at: string;
};

type Quota = {
  personal: { quota_bytes: number; used_bytes: number };
  team: { id: string; name: string; quota_bytes: number; used_bytes: number } | null;
  remaining_bytes: number;
  warning: string | null;
};

type Device = {
  id: string;
  name: string;
  serial: string;
  status: string;
  computed_status?: string | null;
  is_preview?: boolean;
};

type Playlist = { id: string; name: string };

type Organization = { id: string; name: string };

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "ready") return "success";
  if (status === "processing") return "warning";
  if (status === "error") return "destructive";
  return "secondary";
}

export default function MediaPage() {
  const [mediaList, setMediaList] = useState<Media[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [isSuperadmin, setIsSuperadmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [view, setView] = useState<"library" | "trash">("library");
  const [quota, setQuota] = useState<Quota | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [renaming, setRenaming] = useState<Media | null>(null);
  const [newName, setNewName] = useState("");
  const [shareMedia, setShareMedia] = useState<Media | null>(null);
  const [myTeam, setMyTeam] = useState<{ id: string; name: string } | null>(null);
  const [origin, setOrigin] = useState<"all" | "mine" | "team">("all");
  const [showMedia, setShowMedia] = useState<Media | null>(null);
  const [showDeviceId, setShowDeviceId] = useState("");
  const [showDuration, setShowDuration] = useState("");
  const [showSending, setShowSending] = useState(false);

  const [plMedia, setPlMedia] = useState<Media | null>(null);
  const [plId, setPlId] = useState("");

  const [previewMedia, setPreviewMedia] = useState<Media | null>(null);
  const [previewPage, setPreviewPage] = useState(0);
  const [previewPageError, setPreviewPageError] = useState(false);

  function openPreview(media: Media) {
    setPreviewPage(0);
    setPreviewPageError(false);
    setPreviewMedia(media);
  }

  function goPreviewPage(delta: number) {
    setPreviewPage((p) => p + delta);
    setPreviewPageError(false);
  }

  async function reload() {
    try {
      const originQs = view === "library" && origin !== "all" ? `&origin=${origin}` : "";
      const [list, q, team] = await Promise.all([
        api.get<Media[]>(`/api/media${view === "trash" ? "?trash=true" : ""}${originQs}`),
        api.get<Quota>("/api/media/quota"),
        api.get<{ id: string; name: string } | null>("/api/teams/mine").catch(() => null),
      ]);
      setMediaList(list);
      setQuota(q);
      setMyTeam(team);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function loadContext() {
    try {
      const [me, deviceList, playlistList] = await Promise.all([
        api.get<{ role: string }>("/api/auth/me"),
        api.get<Device[]>("/api/devices"),
        api.get<Playlist[]>("/api/playlists"),
      ]);
      setDevices(deviceList);
      setPlaylists(playlistList);
      if (me.role === "superadmin") {
        const items = await api.get<Organization[]>("/api/organizations");
        setIsSuperadmin(true);
        setOrganizations(items);
        setSelectedOrgId((current) => current || items[0]?.id || "");
      }
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  useEffect(() => {
    loadContext();

    reload();
  }, [view, origin]);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        if (isSuperadmin && selectedOrgId) {
          form.append("org_id", selectedOrgId);
        }
        await api.post("/api/media", form);
      }
      setNotice(`${files.length} média(s) envoyé(s) — traitement en cours.`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setUploading(false);
      if (fileRef.current) {
        fileRef.current.value = "";
      }
    }
  }

  async function remove(media: Media) {
    if (!window.confirm(`Mettre « ${media.name} » à la corbeille ?`)) return;
    try {
      await api.del(`/api/media/${media.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function restore(media: Media) {
    try {
      await api.post(`/api/media/${media.id}/restore`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function purge(media: Media) {
    if (!window.confirm(`Supprimer définitivement « ${media.name} » ? Irréversible.`)) return;
    try {
      await api.del(`/api/media/${media.id}/permanent`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function emptyTrash() {
    if (!window.confirm("Vider toute la corbeille ? Irréversible.")) return;
    try {
      await api.post("/api/media/trash/empty");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function share(media: Media) {
    if (!myTeam) return;
    try {
      await api.post(`/api/media/${media.id}/share`, { team_id: myTeam.id });
      setNotice(`« ${media.name} » partagé avec l'équipe « ${myTeam.name} ».`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function rename(media: Media) {
    if (!newName.trim()) return;
    try {
      await api.patch(`/api/media/${media.id}`, { name: newName.trim() });
      setRenaming(null);
      setNewName("");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  function previewUrl(media: Media): string {
    // PDF et Office (convertis en pages PNG) : on affiche la première page.
    if (media.kind === "pdf" || media.kind === "office") {
      return `/api/media/${media.id}/pages/0/preview-file`;
    }
    return `/api/media/${media.id}/preview-file`;
  }

  async function confirmShow() {
    if (!showMedia) return;
    setShowSending(true);
    setError(null);
    try {
      await api.post(`/api/media/${showMedia.id}/show`, {
        device_id: showDeviceId,
        duration_seconds: showDuration ? Number(showDuration) : null,
      });
      setNotice(`« ${showMedia.name} » envoyé sur ${deviceName(showDeviceId)}.`);
      setShowMedia(null);
      setShowDeviceId("");
      setShowDuration("");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setShowSending(false);
    }
  }

  async function confirmAddToPlaylist() {
    if (!plMedia || !plId) return;
    setError(null);
    try {
      await api.post(`/api/media/${plMedia.id}/playlists/${plId}`);
      setNotice(`« ${plMedia.name} » ajouté à la playlist « ${playlistName(plId)} ».`);
      setPlMedia(null);
      setPlId("");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  function deviceName(deviceId: string): string {
    const found = devices.find((d) => d.id === deviceId);
    return found ? found.name : "Raspberry";
  }

  function playlistName(playlistId: string): string {
    const found = playlists.find((p) => p.id === playlistId);
    return found ? found.name : "playlist";
  }

  const targetable = devices.filter(
    (d) => d.status !== "pending" && d.status !== "blocked" && d.status !== "disabled"
  );
  const shownList = mediaList; // filtre serveur ; pagination client dessous
  const totalPages = Math.max(1, Math.ceil(shownList.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pagedList = shownList.slice((safePage - 1) * pageSize, safePage * pageSize);
  const quotaPct =
    quota && quota.personal.quota_bytes > 0
      ? Math.min(100, Math.round((quota.personal.used_bytes / quota.personal.quota_bytes) * 100))
      : 0;
  const teamPct =
    quota?.team && quota.team.quota_bytes > 0
      ? Math.min(100, Math.round((quota.team.used_bytes / quota.team.quota_bytes) * 100))
      : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Médias</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Images, vidéos, PDF et documents Office (les présentations sont
            converties en diaporama). Le titre est modifiable via le crayon.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {isSuperadmin && (
            <label className="space-y-1 text-xs font-medium text-muted-foreground">
              Organisation cible
              <select
                className="flex h-9 min-w-52 rounded-md border border-input bg-card px-3 py-1 text-sm font-normal text-foreground shadow-sm"
                value={selectedOrgId}
                onChange={(e) => setSelectedOrgId(e.target.value)}
              >
                <option value="">Organisation par défaut</option>
                {organizations.map((org) => (
                  <option key={org.id} value={org.id}>{org.name}</option>
                ))}
              </select>
            </label>
          )}
          <Input
            ref={fileRef}
            type="file"
            multiple
            accept="image/*,video/*,application/pdf,.pptx,.ppt,.odp,.docx,.doc,.odt,.xlsx,.xls,.ods"
            disabled={uploading}
            onChange={(e) => upload(e.target.files)}
            className="w-full sm:w-72"
          />
          <div className="flex overflow-hidden rounded-md border">
            <Button
              variant={view === "library" ? "default" : "ghost"}
              size="sm"
              className="rounded-none border-0"
              onClick={() => {
                setView("library");
                setPage(1);
              }}
            >
              Bibliothèque
            </Button>
            <Button
              variant={view === "trash" ? "default" : "ghost"}
              size="sm"
              className="rounded-none border-0"
              onClick={() => {
                setView("trash");
                setPage(1);
              }}
            >
              Corbeille
            </Button>
          </div>
          {myTeam && view === "library" && (
            <div className="flex overflow-hidden rounded-md border">
              {(
                [
                  ["all", "Tous"],
                  ["mine", "Mes médias"],
                  ["team", `Équipe « ${myTeam.name} »`],
                ] as const
              ).map(([value, label]) => (
                <Button
                  key={value}
                  variant={origin === value ? "default" : "ghost"}
                  size="sm"
                  className="rounded-none border-0"
                  onClick={() => {
                    setOrigin(value);
                    setPage(1);
                  }}
                >
                  {label}
                </Button>
              ))}
            </div>
          )}
        </div>
      </div>
      {!isSuperadmin && <OrgScopeNotice />}
      {quota && (
        <div className={"grid gap-3 " + (quota.team ? "sm:grid-cols-2 lg:grid-cols-3" : "sm:grid-cols-2")}>
          <Card className="p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Mon espace ({quota.personal.quota_bytes > 0 ? formatBytes(quota.personal.quota_bytes) : "illimité"})
            </p>
            <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={"h-full rounded-full transition-all " + (quotaPct >= 95 ? "bg-destructive" : quotaPct >= 75 ? "bg-amber-500" : "bg-emerald-500")}
                style={{ width: `${quotaPct}%` }}
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatBytes(quota.personal.used_bytes)} utilisés
            </p>
          </Card>
          {quota.team && (
            <Card className="p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Équipe « {quota.team.name} » ({quota.team.quota_bytes > 0 ? formatBytes(quota.team.quota_bytes) : "illimité"})
              </p>
              <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={"h-full rounded-full transition-all " + (teamPct >= 95 ? "bg-destructive" : teamPct >= 75 ? "bg-amber-500" : "bg-emerald-500")}
                  style={{ width: `${teamPct}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatBytes(quota.team.used_bytes)} utilisés (partagés)
              </p>
            </Card>
          )}
        </div>
      )}
      {quota?.warning && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
          <span>⚠ {quota.warning}</span>
          {view === "trash" ? (
            <Button size="sm" variant="destructive" onClick={emptyTrash}>Vider la corbeille</Button>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setView("trash")}>Voir la corbeille</Button>
          )}
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {notice && <p className="text-sm text-emerald-600">{notice}</p>}
      {uploading && <p className="text-sm text-muted-foreground">Envoi en cours…</p>}

      <Card>
        <CardHeader className="flex-col gap-3 space-y-0 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>{view === "trash" ? "Corbeille" : "Bibliothèque"}</CardTitle>
            <CardDescription>
              {view === "trash"
                ? "Médias corbeillés — restaurables ; purge automatique après 30 jours."
                : "Vidéos (H.264/AAC, WebM…), images (PNG, JPG, GIF animé…), PDF et Office (PowerPoint → diaporama)."}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <select
              className="h-8 rounded-md border border-input bg-card px-2 text-sm"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              aria-label="Médias par page"
            >
              <option value={12}>12 / page</option>
              <option value={24}>24 / page</option>
              <option value={48}>48 / page</option>
            </select>
            {view === "trash" && (
              <Button size="sm" variant="destructive" onClick={emptyTrash}>Vider</Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {pagedList.map((media, index) => (
              <Card
                key={media.id}
                className="animate-rise transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md"
                style={{ animationDelay: `${Math.min(index * 40, 400)}ms` }}
              >
                <button
                  type="button"
                  className="flex h-28 w-full cursor-pointer items-center justify-center overflow-hidden rounded-t-[calc(0.75rem-1px)] bg-muted transition-opacity hover:opacity-90"
                  title="Prévisualiser"
                  onClick={() => openPreview(media)}
                >
                  {media.kind === "video" ? (
                    <video
                      className="max-h-28"
                      src={`/api/media/${media.id}/preview-file`}
                      playsInline
                      muted
                      loop
                      autoPlay
                      preload="metadata"
                    />
                  ) : (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      className="max-h-32 object-contain"
                      src={previewUrl(media)}
                      alt={media.name}
                    />
                  )}
                </button>
                <CardContent className="space-y-1 p-3">
                  {renaming?.id === media.id ? (
                    <div className="flex gap-1">
                      <Input
                        autoFocus
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void rename(media);
                          if (e.key === "Escape") setRenaming(null);
                        }}
                        className="h-7 text-sm"
                      />
                      <Button size="sm" onClick={() => void rename(media)}>✓</Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <p className="truncate text-sm font-medium" title={media.name}>
                        {media.name}
                      </p>
                      <span className="shrink-0 text-[10px] uppercase text-muted-foreground">
                        {(media.original_filename.split(".").pop() || "").slice(0, 4)}
                      </span>
                      <button
                        type="button"
                        className="text-muted-foreground transition-colors hover:text-primary"
                        title="Renommer"
                        onClick={() => {
                          setRenaming(media);
                          setNewName(media.name);
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                    <Badge variant="secondary">{media.kind}</Badge>
                    <Badge variant={statusVariant(media.status)}>{media.status}</Badge>
                    {formatBytes(media.size_bytes)}
                  </div>
                  {view !== "trash" && (
                    <div className="flex items-center gap-0.5 pt-0.5">
                      <button
                        type="button"
                        title="Télécharger"
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        onClick={() => window.open(`/api/media/${media.id}/download`, "_blank")}
                      >
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Afficher sur un écran"
                        disabled={targetable.length === 0}
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                        onClick={() => {
                          setShowMedia(media);
                          setShowDeviceId(targetable[0]?.id ?? "");
                          setShowDuration("");
                        }}
                      >
                        <Eye className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Ajouter à la playliste"
                        disabled={playlists.length === 0}
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                        onClick={() => {
                          setPlMedia(media);
                          setPlId(playlists[0]?.id ?? "");
                        }}
                      >
                        <ListPlus className="h-3.5 w-3.5" />
                      </button>
                      {myTeam && !media.team_name && (
                        <button
                          type="button"
                          title="Partager avec mon équipe"
                          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          onClick={() => setShareMedia(media)}
                        >
                          <Share2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        title="Mettre à la corbeille"
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
                        onClick={() => void remove(media)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                  {media.team_name && (
                    <p className="text-xs text-sky-600 dark:text-sky-400">
                      <Share2 className="mr-1 inline h-3 w-3" />
                      partagé · {media.team_name}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center justify-between gap-1 pt-1">
                    <span className="text-xs text-muted-foreground" title={formatDate(media.created_at)}>
                      {media.width && media.height ? `${media.width}×${media.height}` : "—"}
                    </span>
                    {view === "trash" && (
                      <div className="flex gap-1">
                        <Button size="sm" variant="outline" onClick={() => restore(media)}>
                          Restaurer
                        </Button>
                        <Button size="sm" variant="destructive" onClick={() => purge(media)}>
                          Supprimer définitivement
                        </Button>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
            {pagedList.length === 0 && (
              <p className="col-span-full text-sm text-muted-foreground">
                {view === "trash"
                  ? "La corbeille est vide."
                  : "Aucun média — envoyez vos premiers fichiers ci-dessus."}
              </p>
            )}
          </div>
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-center gap-2">
              <Button size="icon" variant="outline" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)} aria-label="Page précédente">
                <ChevronLeft />
              </Button>
              <span className="text-sm text-muted-foreground">Page {safePage} / {totalPages}</span>
              <Button size="icon" variant="outline" disabled={safePage >= totalPages} onClick={() => setPage(safePage + 1)} aria-label="Page suivante">
                <ChevronRight />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={showMedia !== null} onOpenChange={(open) => !open && setShowMedia(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Afficher « {showMedia?.name ?? ""} »</DialogTitle>
            <DialogDescription>
              Le média sera diffusé immédiatement sur le Raspberry choisi, sans
              modifier les plannings publiés.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="show-device">Raspberry cible</Label>
              <Select
                id="show-device"
                value={showDeviceId}
                onChange={(e) => setShowDeviceId(e.target.value)}
              >
                {targetable.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.name}
                    {device.is_preview ? " (aperçu)" : ""}
                  </option>
                ))}
              </Select>
            </div>
            {showMedia?.kind !== "video" && (
              <div className="space-y-1">
                <Label htmlFor="show-duration">Durée (secondes, facultatif)</Label>
                <Input
                  id="show-duration"
                  type="number"
                  min={1}
                  value={showDuration}
                  onChange={(e) => setShowDuration(e.target.value)}
                  placeholder="10"
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowMedia(null)}>
              Annuler
            </Button>
            <Button onClick={confirmShow} disabled={!showDeviceId || showSending}>
              {showSending ? "Envoi…" : "Afficher"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={shareMedia !== null} onOpenChange={(open) => !open && setShareMedia(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Partager « {shareMedia?.name ?? ""} »</DialogTitle>
            <DialogDescription>
              Le média rejoindra la bibliothèque de l&apos;équipe : tous ses membres
              pourront l&apos;afficher et l&apos;utiliser. Cette action est définitive.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md border p-3 text-sm">
            Équipe : <strong>{myTeam?.name ?? "—"}</strong>
            {quota?.team && (
              <p className="mt-1 text-xs text-muted-foreground">
                Quota équipe : {formatBytes(quota.team.used_bytes)} utilisés sur{" "}
                {quota.team.quota_bytes > 0 ? formatBytes(quota.team.quota_bytes) : "illimité"}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShareMedia(null)}>
              Annuler
            </Button>
            <Button
              disabled={!myTeam}
              onClick={() => {
                if (shareMedia) void share(shareMedia);
                setShareMedia(null);
              }}
            >
              <FolderInput /> Partager
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={plMedia !== null} onOpenChange={(open) => !open && setPlMedia(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ajouter « {plMedia?.name ?? ""} »</DialogTitle>
            <DialogDescription>
              Choisissez la playliste dans laquelle insérer ce média (en fin de séquence).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="pl-target">Playliste</Label>
            <Select id="pl-target" value={plId} onChange={(e) => setPlId(e.target.value)}>
              {playlists.map((playlist) => (
                <option key={playlist.id} value={playlist.id}>
                  {playlist.name}
                </option>
              ))}
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPlMedia(null)}>
              Annuler
            </Button>
            <Button onClick={confirmAddToPlaylist} disabled={!plId}>
              Ajouter
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={previewMedia !== null} onOpenChange={(open) => !open && setPreviewMedia(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              Prévisualisation
              {previewMedia && <Badge variant="secondary">{previewMedia.kind}</Badge>}
            </DialogTitle>
            <DialogDescription>{previewMedia?.name}</DialogDescription>
          </DialogHeader>
          <div className="flex min-h-[280px] items-center justify-center rounded-md bg-muted/50 p-2">
            {previewMedia?.kind === "video" ? (
              <video
                key={previewMedia.id}
                controls
                autoPlay
                playsInline
                className="max-h-[65vh] w-full"
                src={`/api/media/${previewMedia.id}/preview-file`}
              />
            ) : previewMedia?.kind === "image" ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                key={previewMedia.id}
                src={`/api/media/${previewMedia.id}/preview-file`}
                alt={previewMedia.name}
                className="max-h-[65vh] object-contain"
              />
            ) : previewMedia ? (
              previewPageError ? (
                <p className="text-sm text-muted-foreground">
                  Aucune page disponible pour ce média.
                </p>
              ) : (
                <div className="flex w-full flex-col items-center gap-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    key={`${previewMedia.id}-${previewPage}`}
                    src={`/api/media/${previewMedia.id}/pages/${previewPage}/preview-file`}
                    alt={`Page ${previewPage + 1}`}
                    onError={() => setPreviewPageError(true)}
                    className="max-h-[58vh] object-contain"
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      size="icon"
                      variant="outline"
                      disabled={previewPage <= 0}
                      onClick={() => goPreviewPage(-1)}
                      aria-label="Page précédente"
                    >
                      <ChevronLeft />
                    </Button>
                    <span className="text-sm text-muted-foreground">
                      Page {previewPage + 1} / {previewMedia.pages_count ?? "?"}
                    </span>
                    <Button
                      size="icon"
                      variant="outline"
                      disabled={
                        previewMedia.pages_count != null &&
                        previewPage >= previewMedia.pages_count - 1
                      }
                      onClick={() => goPreviewPage(1)}
                      aria-label="Page suivante"
                    >
                      <ChevronRight />
                    </Button>
                  </div>
                </div>
              )
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPreviewMedia(null)}>
              Fermer
            </Button>
            <Button
              onClick={() =>
                previewMedia && window.open(`/api/media/${previewMedia.id}/download`, "_blank")
              }
            >
              <Download /> Télécharger
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
