"use client";

import { useEffect, useRef, useState } from "react";
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
  created_at: string;
};

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "ready") return "success";
  if (status === "processing") return "warning";
  if (status === "error") return "destructive";
  return "secondary";
}

export default function MediaPage() {
  const [mediaList, setMediaList] = useState<Media[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reload() {
    try {
      setMediaList(await api.get<Media[]>("/api/media"));
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        await api.post("/api/media?name=", form);
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
    if (!window.confirm(`Supprimer « ${media.name} » ?`)) return;
    try {
      await api.del(`/api/media/${media.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  function previewUrl(media: Media): string {
    if (media.kind === "pdf") {
      return `/api/media/${media.id}/pages/0/file`;
    }
    return `/api/media/${media.id}/file`;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Médias</h1>
      <OrgScopeNotice />
        <div>
          <Input
            ref={fileRef}
            type="file"
            multiple
            accept="image/*,video/*,application/pdf"
            disabled={uploading}
            onChange={(e) => upload(e.target.files)}
            className="w-72"
          />
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {notice && <p className="text-sm text-emerald-600">{notice}</p>}
      {uploading && <p className="text-sm text-muted-foreground">Envoi en cours…</p>}

      <Card>
        <CardHeader>
          <CardTitle>Bibliothèque</CardTitle>
          <CardDescription>
            Images, vidéos (H.264/AAC) et PDF — les PDF sont convertis page par page.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {mediaList.map((media) => (
              <Card key={media.id} className="overflow-hidden">
                <div className="flex h-32 items-center justify-center bg-muted">
                  {media.kind === "video" ? (
                    <video
                      className="max-h-32"
                      src={`/api/media/${media.id}/file`}
                      muted
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
                </div>
                <CardContent className="space-y-1 p-3">
                  <p className="truncate text-sm font-medium" title={media.name}>
                    {media.name}
                  </p>
                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Badge variant="secondary">{media.kind}</Badge>
                    <Badge variant={statusVariant(media.status)}>{media.status}</Badge>
                    {formatBytes(media.size_bytes)}
                  </div>
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-xs text-muted-foreground" title={formatDate(media.created_at)}>
                      {media.width && media.height ? `${media.width}×${media.height}` : "—"}
                    </span>
                    <Button size="sm" variant="destructive" onClick={() => remove(media)}>
                      Supprimer
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
            {mediaList.length === 0 && (
              <p className="col-span-full text-sm text-muted-foreground">
                Aucun média — envoyez vos premiers fichiers ci-dessus.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
