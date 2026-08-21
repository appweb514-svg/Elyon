"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowDown, ArrowUp } from "lucide-react";
import { api } from "@/lib/api";
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

type Media = { id: string; name: string; kind: string };

type Item = {
  id: string;
  media_id: string;
  position: number;
  duration_seconds: number | null;
};

type PlaylistDetail = {
  id: string;
  name: string;
  description: string | null;
  items: Item[];
};

export default function PlaylistDetailPage() {
  const params = useParams<{ id: string }>();
  const playlistId = params.id;
  const [playlist, setPlaylist] = useState<PlaylistDetail | null>(null);
  const [mediaList, setMediaList] = useState<Media[]>([]);
  const [mediaById, setMediaById] = useState<Record<string, Media>>({});
  const [selectedMedia, setSelectedMedia] = useState("");
  const [duration, setDuration] = useState("10");
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [detail, media] = await Promise.all([
        api.get<PlaylistDetail>(`/api/playlists/${playlistId}`),
        api.get<Media[]>("/api/media"),
      ]);
      setPlaylist(detail);
      setMediaList(media);
      const byId: Record<string, Media> = {};
      for (const item of media) {
        byId[item.id] = item;
      }
      setMediaById(byId);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [playlistId]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function addItem() {
    if (!selectedMedia) return;
    try {
      const seconds = Number.parseInt(duration, 10);
      await api.post(`/api/playlists/${playlistId}/items`, {
        media_id: selectedMedia,
        duration_seconds: Number.isNaN(seconds) || seconds < 1 ? null : seconds,
      });
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function removeItem(item: Item) {
    try {
      await api.del(`/api/playlists/${playlistId}/items/${item.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function move(item: Item, direction: -1 | 1) {
    if (!playlist) return;
    const ids = [...playlist.items]
      .sort((a, b) => a.position - b.position)
      .map((i) => i.id);
    const index = ids.indexOf(item.id);
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    try {
      const updated = await api.post<PlaylistDetail>(`/api/playlists/${playlistId}/reorder`, ids);
      setPlaylist(updated);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  if (error && !playlist) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (!playlist) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }

  const sorted = [...playlist.items].sort((a, b) => a.position - b.position);

  return (
    <div className="space-y-6">
      <div>
        <Link href="/playlists" className="text-sm text-muted-foreground hover:underline">
          ← Playlists
        </Link>
        <h1 className="text-2xl font-bold">{playlist.name}</h1>
        {playlist.description && (
          <p className="text-sm text-muted-foreground">{playlist.description}</p>
        )}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Ajouter un média</CardTitle>
          <CardDescription>
            La durée par défaut s&apos;applique aux images et pages PDF (les vidéos jouent
            jusqu&apos;à leur fin).
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-[3fr_1fr_1fr] sm:items-end">
          <div className="space-y-2">
            <Label htmlFor="item-media">Média</Label>
            <Select
              id="item-media"
              value={selectedMedia}
              onChange={(e) => setSelectedMedia(e.target.value)}
            >
              <option value="">— Choisir —</option>
              {mediaList.map((media) => (
                <option key={media.id} value={media.id}>
                  {media.name} ({media.kind})
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="item-duration">Durée (s)</Label>
            <Input
              id="item-duration"
              type="number"
              min={1}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </div>
          <Button onClick={addItem} disabled={!selectedMedia}>
            Ajouter
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Séquence ({sorted.length} élément{sorted.length > 1 ? "s" : ""})</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">#</TableHead>
                <TableHead>Média</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Durée</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((item, index) => {
                const media = mediaById[item.media_id];
                return (
                  <TableRow key={item.id}>
                    <TableCell>{index + 1}</TableCell>
                    <TableCell className="font-medium">{media?.name ?? item.media_id}</TableCell>
                    <TableCell>{media?.kind ?? "—"}</TableCell>
                    <TableCell>
                      {item.duration_seconds ? `${item.duration_seconds} s` : "fin de lecture"}
                    </TableCell>
                    <TableCell className="space-x-1 text-right">
                      <Button
                        size="icon"
                        variant="ghost"
                        disabled={index === 0}
                        onClick={() => move(item, -1)}
                        aria-label="Monter"
                      >
                        <ArrowUp />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        disabled={index === sorted.length - 1}
                        onClick={() => move(item, 1)}
                        aria-label="Descendre"
                      >
                        <ArrowDown />
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => removeItem(item)}>
                        Retirer
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {sorted.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Playlist vide — ajoutez des médias ci-dessus.
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
