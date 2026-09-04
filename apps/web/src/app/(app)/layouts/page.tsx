"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { LayoutGrid, MapPin, Monitor, PenSquare } from "lucide-react";

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

type ScreenLayout = {
  mode: string;
  zones: Array<{ x: number; y: number; w: number; h: number }>;
};

type Screen = {
  id: string;
  site_id: string;
  name: string;
  width: number;
  height: number;
  orientation: string;
  device_id: string | null;
  layout: ScreenLayout | null;
  created_at: string;
};

type Site = { id: string; name: string };

const MODE_LABEL: Record<string, string> = {
  fullscreen: "Plein écran",
  split_h: "2 zones H",
  split_v: "2 zones V",
  grid_2x2: "Grille 2×2",
  custom: "Personnalisé",
};

function LayoutPreview({ layout }: { layout: ScreenLayout }) {
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-md border bg-muted/40">
      {layout.zones.map((z, i) => (
        <div
          key={i}
          className="absolute flex items-center justify-center rounded border border-primary/40 bg-primary/15 text-[10px] font-semibold text-primary"
          style={{
            left: `${z.x}%`,
            top: `${z.y}%`,
            width: `${z.w}%`,
            height: `${z.h}%`,
          }}
        >
          {i + 1}
        </div>
      ))}
    </div>
  );
}

export default function LayoutsPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [screens, setScreens] = useState<Screen[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const siteList = await api.get<Site[]>("/api/sites");
      setSites(siteList);
      const all: Screen[] = [];
      for (const site of siteList) {
        const screens = await api.get<Screen[]>(`/api/sites/${site.id}/screens`);
        all.push(...screens);
      }
      setScreens(all);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const siteName = (id: string) => sites.find((s) => s.id === id)?.name ?? id;
  const withLayout = screens.filter((s) => s.layout);
  const withoutLayout = screens.filter((s) => !s.layout);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dispositions</h1>
        <p className="text-sm text-muted-foreground">
          Configuration visuelle des écrans (zones, médias, playlists). Chaque disposition
          est enregistrée sur l&apos;écran puis incluse au manifeste lors de la publication.
        </p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LayoutGrid className="h-5 w-5 text-primary" /> Vue d&apos;ensemble
            </CardTitle>
            <CardDescription>Répartition des écrans par configuration</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border p-3">
              <span className="flex items-center gap-2 text-sm">
                <Monitor className="h-4 w-4 text-muted-foreground" /> Écrans configurés
              </span>
              <Badge variant="success">{withLayout.length}</Badge>
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <span className="flex items-center gap-2 text-sm">
                <PenSquare className="h-4 w-4 text-muted-foreground" /> À configurer
              </span>
              <Badge
                variant={withoutLayout.length > 0 ? "warning" : "secondary"}
              >
                {withoutLayout.length}
              </Badge>
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <span className="flex items-center gap-2 text-sm">
                <MapPin className="h-4 w-4 text-muted-foreground" /> Sites
              </span>
              <Badge variant="secondary">{sites.length}</Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              Depuis la fiche d&apos;un appareil, le même éditeur permet de sauvegarder la
              disposition puis de publier le manifeste.
            </p>
          </CardContent>
        </Card>

        <div className="lg:col-span-2 space-y-6">
          <section className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Écrans configurés ({withLayout.length})
            </h2>
            {withLayout.length === 0 ? (
              <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                Aucune disposition configurée pour le moment.
              </p>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                {withLayout.map((screen) => (
                  <Card key={screen.id} className="animate-rise overflow-hidden transition-shadow hover:shadow-md">
                    <CardContent className="p-4 space-y-3">
                      <LayoutPreview layout={screen.layout as ScreenLayout} />
                      <div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="truncate text-sm font-semibold">{screen.name}</p>
                          <Badge variant="secondary">
                            {MODE_LABEL[screen.layout?.mode ?? ""] ?? screen.layout?.mode}
                          </Badge>
                        </div>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {siteName(screen.site_id)} · {screen.width}×{screen.height} ·{" "}
                          {screen.layout ? screen.layout.zones.length : 0} zone(s)
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-[11px] text-muted-foreground">
                          Créé {formatDate(screen.created_at)}
                        </span>
                        {screen.device_id ? (
                          <Button size="sm" variant="outline" asChild>
                            <Link href={`/devices/${screen.device_id}/layout`}>Ouvrir l&apos;éditeur</Link>
                          </Button>
                        ) : (
                          <span className="text-[11px] text-muted-foreground">
                            Aucun device assigné
                          </span>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </section>

          {withoutLayout.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Écrans sans disposition ({withoutLayout.length})
              </h2>
              <div className="rounded-lg border">
                {withoutLayout.map((screen) => (
                  <div
                    key={screen.id}
                    className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 last:border-b-0"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{screen.name}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {siteName(screen.site_id)} · {screen.width}×{screen.height} {screen.orientation}
                      </p>
                    </div>
                    {screen.device_id ? (
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/devices/${screen.device_id}/layout`}>Configurer</Link>
                      </Button>
                    ) : (
                      <Badge variant="warning">device non assigné</Badge>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
