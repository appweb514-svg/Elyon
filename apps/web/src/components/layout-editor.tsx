"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

export type LayoutZone = {
  x: number;
  y: number;
  w: number;
  h: number;
  media_id?: string | null;
  playlist_id?: string | null;
};

export type ScreenLayout = {
  mode: string;
  zones: LayoutZone[];
};

const MODES = [
  { value: "fullscreen", label: "Plein écran (1 zone)" },
  { value: "split_h", label: "2 zones horizontales" },
  { value: "split_v", label: "2 zones verticales" },
  { value: "grid_2x2", label: "Grille 2×2 (4 zones)" },
  { value: "custom", label: "Personnalisé" },
];

function defaultZones(mode: string): LayoutZone[] {
  if (mode === "fullscreen") return [{ x: 0, y: 0, w: 100, h: 100 }];
  if (mode === "split_h") return [{ x: 0, y: 0, w: 100, h: 50 }, { x: 0, y: 50, w: 100, h: 50 }];
  if (mode === "split_v") return [{ x: 0, y: 0, w: 50, h: 100 }, { x: 50, y: 0, w: 50, h: 100 }];
  if (mode === "grid_2x2")
    return [
      { x: 0, y: 0, w: 50, h: 50 },
      { x: 50, y: 0, w: 50, h: 50 },
      { x: 0, y: 50, w: 50, h: 50 },
      { x: 50, y: 50, w: 50, h: 50 },
    ];
  return [{ x: 0, y: 0, w: 100, h: 100 }];
}

export function LayoutEditor({
  value,
  onChange,
  mediaOptions,
  playlistOptions,
}: {
  value: ScreenLayout | null;
  onChange: (v: ScreenLayout | null) => void;
  mediaOptions: Array<{ id: string; name: string }>;
  playlistOptions: Array<{ id: string; name: string }>;
}) {
  const [mode, setMode] = useState(value?.mode ?? "fullscreen");
  const [zones, setZones] = useState<LayoutZone[]>(value?.zones ?? defaultZones("fullscreen"));

  useEffect(() => {
    if (value) {
      setMode(value.mode);
      setZones(value.zones);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync externe value → état local uniquement à l'arrivée d'une nouvelle valeur
  }, [value?.mode, value?.zones]);

  function applyMode(newMode: string) {
    setMode(newMode);
    const nz = defaultZones(newMode);
    // preserve media/playlist if same count
    if (zones.length === nz.length) {
      for (let i = 0; i < nz.length; i++) {
        nz[i].media_id = zones[i].media_id;
        nz[i].playlist_id = zones[i].playlist_id;
      }
    }
    setZones(nz);
    onChange({ mode: newMode, zones: nz });
  }

  function updateZone(idx: number, patch: Partial<LayoutZone>) {
    const nz = zones.map((z, i) => (i === idx ? { ...z, ...patch } : z));
    setZones(nz);
    onChange({ mode, zones: nz });
  }

  function addZone() {
    const nz = [...zones, { x: 0, y: 0, w: 50, h: 50 }];
    setZones(nz);
    onChange({ mode: "custom", zones: nz });
    setMode("custom");
  }

  function removeZone(idx: number) {
    const nz = zones.filter((_, i) => i !== idx);
    setZones(nz);
    onChange({ mode: "custom", zones: nz });
    setMode("custom");
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Mode de disposition</Label>
        <Select data-testid="mode-select" value={mode} onChange={(e) => applyMode(e.target.value)}>
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </Select>
        <p className="text-xs text-muted-foreground">
          Positions et tailles en pourcentage (0–100). Le player ignore un layout inconnu (MVP : zones statiques).
        </p>
      </div>

      <div className="relative aspect-video rounded-md border bg-muted p-2">
        <div className="relative h-full w-full overflow-hidden rounded bg-card">
          {zones.map((z, idx) => (
            <div
              key={idx}
              className="absolute flex items-center justify-center border border-dashed border-primary/50 bg-primary/10 text-xs font-medium"
              style={{
                left: `${z.x}%`,
                top: `${z.y}%`,
                width: `${z.w}%`,
                height: `${z.h}%`,
              }}
            >
              Zone {idx + 1}
            </div>
          ))}
        </div>
      </div>

      {zones.map((z, idx) => (
        <div key={idx} className="rounded-md border p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">Zone {idx + 1}</span>
            <Button size="sm" variant="ghost" onClick={() => removeZone(idx)}>
              Retirer
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {(["x", "y", "w", "h"] as const).map((k) => (
              <div key={k} className="space-y-1">
                <Label className="text-xs">{k.toUpperCase()} %</Label>
                <Input
                  data-testid={`zone-${idx}-${k}`}
                  type="number"
                  min={0}
                  max={100}
                  value={z[k]}
                  onChange={(e) => updateZone(idx, { [k]: Number(e.target.value) } as Partial<LayoutZone>)}
                />
              </div>
            ))}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">Média</Label>
              <Select
                value={z.media_id ?? ""}
                onChange={(e) => updateZone(idx, { media_id: e.target.value || null, playlist_id: null })}
              >
                <option value="">— Aucun —</option>
                {mediaOptions.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Playlist</Label>
              <Select
                value={z.playlist_id ?? ""}
                onChange={(e) => updateZone(idx, { playlist_id: e.target.value || null, media_id: null })}
              >
                <option value="">— Aucune —</option>
                {playlistOptions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        </div>
      ))}

      <Button data-testid="add-zone" variant="outline" size="sm" onClick={addZone}>
        Ajouter une zone
      </Button>
    </div>
  );
}
