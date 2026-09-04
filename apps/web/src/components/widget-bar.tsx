"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Eye, EyeOff, Rss, Settings2, CloudSun, Type, Clock3, Code2, X } from "lucide-react";

export type Widget = {
  id?: string;
  type: string; // weather | rss | text | clock | html
  position: string; // top-left | top-right | bottom-left | bottom-center | bottom-right | bottom-ticker
  visible: boolean;
  locked?: boolean; // widget de barre (haut/bas) : position non modifiable
  params: Record<string, string | number | null>;
};

const TYPE_META: Record<string, { label: string; icon: typeof CloudSun }> = {
  weather: { label: "Météo", icon: CloudSun },
  rss: { label: "Flux RSS", icon: Rss },
  text: { label: "Texte libre", icon: Type },
  clock: { label: "Horloge", icon: Clock3 },
  html: { label: "HTML", icon: Code2 },
};

const POSITIONS = [
  { value: "bottom-left", label: "Bas gauche" },
  { value: "bottom-center", label: "Bas centre" },
  { value: "bottom-right", label: "Bas droite" },
];

/** Widget verrouillé = élément d'une barre (météo/horloge en haut, ticker RSS en bas). */
function isBarWidget(w: Widget): boolean {
  return w.locked === true || ["top-left", "top-right", "bottom-ticker"].includes(w.position);
}

/** Code WMO (Open-Meteo) → icône météo. */
function weatherEmoji(code?: number | null): string {
  if (code == null) return "☁️";
  if (code === 0) return "☀️";
  if (code <= 2) return "⛅";
  if (code === 3) return "☁️";
  if (code === 45 || code === 48) return "🌫️";
  if (code <= 67) return "🌧️";
  if (code <= 77) return "❄️";
  if (code <= 82) return "🌧️";
  if (code <= 86) return "❄️";
  return "⛈️";
}

const FR_DAYS = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"];

function dayLabel(dateStr: string | undefined, index: number): string {
  if (!dateStr) return FR_DAYS[index % 7];
  const d = new Date(`${dateStr.slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? FR_DAYS[index % 7] : FR_DAYS[d.getDay()];
}

type ForecastDay = { date?: string; max?: number; min?: number; code?: number };

function ForecastRow({ forecast }: { forecast: ForecastDay[] }) {
  const days = forecast.filter((f) => typeof f.max === "number" && typeof f.min === "number").slice(0, 5);
  if (days.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-x-2 gap-y-0.5">
      {days.map((f, i) => (
        <span key={f.date ?? i} className="whitespace-nowrap">
          {weatherEmoji(f.code)} {dayLabel(f.date, i)} {Math.round(f.max!)}°/{Math.round(f.min!)}°
        </span>
      ))}
    </span>
  );
}

const SAMPLE_FORECAST: ForecastDay[] = [
  { date: "", max: 24, min: 15, code: 1 },
  { date: "", max: 22, min: 14, code: 61 },
  { date: "", max: 19, min: 13, code: 3 },
  { date: "", max: 21, min: 12, code: 0 },
];

/** Barre de widgets : liste + édition inline (position, paramètres, visibilité).
 *
 * `openId` est contrôlé par le parent (persistant à travers les re-renders) :
 * le rechargement périodique de la page ne referme plus le menu de réglages.
 */
export function WidgetBar({
  widgets,
  onChange,
  openId,
  onOpenChange,
}: {
  widgets: Widget[];
  onChange: (widgets: Widget[]) => void;
  openId: string | null;
  onOpenChange: (id: string | null) => void;
}) {
  const [preview, setPreview] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const previewRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ id: string; index: number } | null>(null);

  function add(type: string) {
    if (widgets.length >= 3) return;
    const meta = TYPE_META[type];
    if (!meta) return;
    const w: Widget = {
      type,
      position: ["bottom-left", "bottom-center", "bottom-right"][widgets.length % 3],
      visible: true,
      params:
        type === "weather"
          ? { city: "Paris" }
          : type === "rss"
            ? { url: "" }
            : type === "text"
              ? { text: "Votre message ici" }
              : type === "clock"
                ? { format: "HH:MM" }
                : { html: "<b>Bonjour</b>" },
    };
    onChange([...widgets, w]);
    onOpenChange(w.id ?? String(widgets.length));
  }

  function update(index: number, patch: Partial<Widget>) {
    const next = widgets.map((w, i) => (i === index ? { ...w, ...patch } : w));
    onChange(next);
  }

  // --- Barres d'information (haut : météo + heure, bas : ticker RSS) ---

  function findBar(type: string): Widget | undefined {
    return widgets.find((w) => w.type === type && isBarWidget(w));
  }

  const topBarEnabled = findBar("weather") !== undefined || findBar("clock") !== undefined;
  const bottomBarEnabled = findBar("rss") !== undefined;

  function toggleTopBar(enable: boolean) {
    const rest = widgets.filter((w) => !(isBarWidget(w) && (w.type === "weather" || w.type === "clock")));
    if (!enable) {
      onChange(rest);
      return;
    }
    onChange([
      ...rest,
      { type: "weather", position: "top-left", visible: true, locked: true, params: { city: "Paris" } },
      { type: "clock", position: "top-right", visible: true, locked: true, params: { format: "HH:MM" } },
    ]);
  }

  function toggleBottomBar(enable: boolean) {
    const rest = widgets.filter((w) => !(isBarWidget(w) && w.type === "rss"));
    if (!enable) {
      onChange(rest);
      return;
    }
    onChange([
      ...rest,
      { type: "rss", position: "bottom-ticker", visible: true, locked: true, params: { url: "" } },
    ]);
  }

  async function previewWeather(index: number, city: string) {
    const key = `w${index}`;
    setLoading(key);
    try {
      const data = await api.get<Record<string, unknown>>(
        `/api/widgets/feed?type=weather&q=${encodeURIComponent(city)}`
      );
      setPreview((p) => ({ ...p, [key]: data }));
    } catch {
      setPreview((p) => ({ ...p, [key]: { error: true } }));
    } finally {
      setLoading(null);
    }
  }

  const selectedIndex = widgets.findIndex((widget, index) => (widget.id ?? String(index)) === openId);
  const selected = selectedIndex >= 0 ? widgets[selectedIndex] : null;

  function widgetPosition(position: string): string {
    switch (position) {
      case "top-left":
        return "top-2 left-2";
      case "top-right":
        return "top-2 right-2";
      case "bottom-right":
        return "right-2";
      case "bottom-ticker":
        return "bottom-0 left-0 right-0";
      case "bottom-center":
        return "left-1/2 -translate-x-1/2";
      default:
        return "left-2";
    }
  }

  function slotFromClientX(
    clientX: number,
    clientY: number,
  ): "bottom-left" | "bottom-center" | "bottom-right" | "top-left" | "top-right" {
    const rect = previewRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return "bottom-left";
    const top = (clientY - rect.top) / rect.height < 0.25;
    const ratio = (clientX - rect.left) / rect.width;
    if (top) return ratio < 0.5 ? "top-left" : "top-right";
    if (ratio < 1 / 3) return "bottom-left";
    if (ratio < 2 / 3) return "bottom-center";
    return "bottom-right";
  }

  function onWidgetDragStart(event: React.DragEvent, w: Widget, index: number) {
    const id = w.id ?? String(index);
    dragRef.current = { id, index };
    setDraggingId(id);
    onOpenChange(null);
    event.dataTransfer.effectAllowed = "move";
    try {
      event.dataTransfer.setData("text/plain", id);
    } catch {
      /* anciens navigateurs */
    }
  }

  function onPreviewDragOver(event: React.DragEvent) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }

  function onPreviewDrop(event: React.DragEvent) {
    event.preventDefault();
    const drag = dragRef.current;
    dragRef.current = null;
    setDraggingId(null);
    if (!drag) return;
    update(drag.index, { position: slotFromClientX(event.clientX, event.clientY) });
  }

  function onWidgetDragEnd() {
    dragRef.current = null;
    setDraggingId(null);
  }

  function renderWidgetContent(widget: Widget) {
    return (
      <>
        {widget.type === "weather" && (
          <span className="flex flex-col gap-0.5">
            <span>{widget.params.city ?? "Ville"} · 12°C {weatherEmoji(1)}</span>
            <ForecastRow forecast={SAMPLE_FORECAST} />
          </span>
        )}
        {widget.type === "rss" &&
          (widget.position === "bottom-ticker"
            ? widget.params.url
              ? "Actualité 1  •  Actualité 2  •  Actualité 3 …"
              : "Configurez l'URL du flux RSS"
            : widget.params.url
              ? "RSS : dernières actualités…"
              : "RSS : configurez l'URL")}
        {widget.type === "text" && String(widget.params.text ?? "")}
        {widget.type === "clock" && <Clock3 className="mr-1 inline h-3.5 w-3.5" />}
        {widget.type === "clock" && (widget.params.format ?? "HH:MM") === "HH:MM:SS" ? "14:32:08" : "14:32"}
        {widget.type === "html" && <span dangerouslySetInnerHTML={{ __html: String(widget.params.html ?? "") }} />}
      </>
    );
  }

  function renderBarToggles() {
    return (
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          role="switch"
          aria-checked={topBarEnabled}
          data-testid="top-bar-toggle"
          onClick={() => toggleTopBar(!topBarEnabled)}
          className={`rounded-md border px-3 py-1.5 text-xs font-medium transition ${topBarEnabled ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted/60"}`}
        >
          Barre du haut : météo à gauche, heure à droite {topBarEnabled ? "✓" : ""}
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={bottomBarEnabled}
          data-testid="bottom-bar-toggle"
          onClick={() => toggleBottomBar(!bottomBarEnabled)}
          className={`rounded-md border px-3 py-1.5 text-xs font-medium transition ${bottomBarEnabled ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted/60"}`}
        >
          Barre du bas : flux RSS défilant {bottomBarEnabled ? "✓" : ""}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {Object.entries(TYPE_META).map(([type, meta]) => {
          const Icon = meta.icon;
          return (
            <Button key={type} type="button" variant="outline" size="sm" onClick={() => add(type)}>
              <Icon /> {meta.label}
            </Button>
          );
        })}
        <span className="text-xs text-muted-foreground">
          Cliquez sur un widget dans l&apos;aperçu pour le configurer, glissez-le pour changer son emplacement (3 maximum).
        </span>
      </div>

      {renderBarToggles()}

      {widgets.length > 0 && (
        <div
          ref={previewRef}
          data-testid="widget-preview"
          onDragOver={onPreviewDragOver}
          onDrop={onPreviewDrop}
          className="relative aspect-video w-full overflow-hidden rounded-lg border bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-900 dark:to-slate-950"
        >
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
            Contenu principal (playlist)
          </div>
          {widgets.map((w, i) => {
            if (!w.visible) return null;
            const id = w.id ?? String(i);
            const isDragging = draggingId === id;
            const pos = widgetPosition(w.position);
            const locked = isBarWidget(w);
            if (w.position === "bottom-ticker") {
              return (
                <button
                  key={id}
                  type="button"
                  className={`absolute bottom-0 left-0 right-0 cursor-pointer overflow-hidden rounded-b-md bg-black/80 px-3 py-1.5 text-left text-xs whitespace-nowrap text-white shadow focus:outline-none focus:ring-2 focus:ring-primary ${isDragging ? "z-20 opacity-70" : ""}`}
                  onClick={() => onOpenChange(id)}
                  aria-label={`Widget ${TYPE_META[w.type]?.label ?? ""} — cliquez pour configurer`}
                >
                  <span className="elyon-ticker inline-block">{renderWidgetContent(w)}</span>
                </button>
              );
            }
            return (
              <button
                key={id}
                type="button"
                draggable={!locked}
                onDragStart={locked ? undefined : (e) => onWidgetDragStart(e, w, i)}
                onDragEnd={locked ? undefined : onWidgetDragEnd}
                className={`absolute bottom-2 ${pos} select-none max-w-[60%] rounded-md bg-black/70 px-3 py-1.5 text-left text-xs text-white shadow transition hover:bg-black/85 focus:outline-none focus:ring-2 focus:ring-primary ${locked ? "cursor-default" : "cursor-grab active:cursor-grabbing"} ${isDragging ? "z-20 opacity-70" : ""}`}
                style={w.position.startsWith("top-") ? { bottom: "auto" } : undefined}
                onClick={() => onOpenChange(id)}
                aria-label={`Widget ${TYPE_META[w.type]?.label ?? ""} — cliquez pour configurer${locked ? "" : ", glissez pour déplacer"}`}
              >
                {renderWidgetContent(w)}
              </button>
            );
          })}
          {selected && selectedIndex >= 0 && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/35 p-3 sm:p-6">
              <div
                role="dialog"
                aria-modal="true"
                aria-label={`Configuration du widget ${TYPE_META[selected.type]?.label ?? ""}`}
                className="max-h-full w-full max-w-md overflow-y-auto rounded-xl border bg-card p-4 text-card-foreground shadow-2xl sm:p-5"
              >
                <div className="mb-4 flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold">Configuration du widget</p>
                    <p className="text-xs text-muted-foreground">Les changements sont visibles immédiatement dans l&apos;aperçu.</p>
                  </div>
                  <Button type="button" size="icon" variant="ghost" onClick={() => onOpenChange(null)} aria-label="Fermer">
                    <X />
                  </Button>
                </div>
                <div className="mb-4 rounded-lg border bg-muted/40 p-3">
                  <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Prévisualisation en temps réel</p>
                  <div className="relative aspect-video overflow-hidden rounded-md bg-gradient-to-br from-slate-200 to-slate-300 dark:from-slate-800 dark:to-slate-950">
                    <div className="flex h-full items-center justify-center text-[10px] text-muted-foreground">Contenu principal</div>
                    <div className={`absolute bottom-2 ${widgetPosition(selected.position)} max-w-[calc(100%-1rem)]`}>
                      <span className="max-w-full rounded-md bg-black/70 px-3 py-1.5 text-xs text-white shadow">
                        {renderWidgetContent(selected)}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {!isBarWidget(selected) && (
                    <div className="space-y-1">
                      <Label className="text-xs">Emplacement</Label>
                      <Select value={selected.position} onChange={(e) => update(selectedIndex, { position: e.target.value })}>
                        {POSITIONS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                      </Select>
                    </div>
                  )}
                  {selected.type === "weather" && (
                    <div className="space-y-1">
                      <Label className="text-xs">Ville</Label>
                      <div className="flex gap-1">
                        <Input value={String(selected.params.city ?? "")} onChange={(e) => update(selectedIndex, { params: { ...selected.params, city: e.target.value } })} placeholder="Paris" />
                        <Button type="button" size="sm" variant="outline" onClick={() => previewWeather(selectedIndex, String(selected.params.city ?? ""))}>Tester</Button>
                      </div>
                      {loading === `w${selectedIndex}` && <p className="text-xs text-muted-foreground">Interrogation…</p>}
                      {preview[`w${selectedIndex}`] != null &&
                        (() => {
                          const data = preview[`w${selectedIndex}`] as {
                            place?: string;
                            temperature?: number;
                            code?: number;
                            forecast?: ForecastDay[];
                          };
                          if (typeof data.temperature !== "number") return <p className="text-xs text-muted-foreground">Ville introuvable</p>;
                          return (
                            <div className="space-y-0.5">
                              <p className="text-xs text-muted-foreground">
                                {data.place} : {Math.round(data.temperature)}°C {weatherEmoji(data.code)}
                              </p>
                              <ForecastRow forecast={data.forecast ?? []} />
                            </div>
                          );
                        })()}
                    </div>
                  )}
                  {selected.type === "rss" && (
                    <div className="space-y-1 sm:col-span-1">
                      <Label className="text-xs">URL du flux RSS</Label>
                      <Input value={String(selected.params.url ?? "")} onChange={(e) => update(selectedIndex, { params: { ...selected.params, url: e.target.value } })} placeholder="https://exemple.fr/rss.xml" />
                    </div>
                  )}
                  {selected.type === "text" && (
                    <div className="space-y-1 sm:col-span-2">
                      <Label className="text-xs">Texte à afficher</Label>
                      <Input value={String(selected.params.text ?? "")} onChange={(e) => update(selectedIndex, { params: { ...selected.params, text: e.target.value } })} />
                    </div>
                  )}
                  {selected.type === "clock" && (
                    <div className="space-y-1">
                      <Label className="text-xs">Format</Label>
                      <Select value={String(selected.params.format ?? "HH:MM")} onChange={(e) => update(selectedIndex, { params: { ...selected.params, format: e.target.value } })}>
                        <option value="HH:MM">Heure:Minute</option>
                        <option value="HH:MM:SS">Heure:Minute:Seconde</option>
                      </Select>
                    </div>
                  )}
                  {selected.type === "html" && (
                    <div className="space-y-1 sm:col-span-2">
                      <Label className="text-xs">HTML à afficher</Label>
                      <Input value={String(selected.params.html ?? "")} onChange={(e) => update(selectedIndex, { params: { ...selected.params, html: e.target.value } })} />
                    </div>
                  )}
                </div>
                <div className="mt-4 flex justify-end">
                  <Button type="button" onClick={() => onOpenChange(null)}>Terminer</Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      <ul className="space-y-2">
        {widgets.map((w, i) => {
          const meta = TYPE_META[w.type] ?? TYPE_META.text;
          const Icon = meta.icon;
          const id = w.id ?? String(i);
          return (
            <li key={id} className="rounded-md border p-3">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-primary" />
                <button type="button" className="min-w-0 flex-1 truncate text-left text-sm font-medium hover:text-primary" onClick={() => onOpenChange(id)}>
                  {meta.label}
                </button>
                <Button type="button" size="icon" variant="ghost" aria-label={w.visible ? "Cacher le widget" : "Afficher le widget"} title={w.visible ? "Cacher" : "Afficher"} onClick={() => update(i, { visible: !w.visible })}>
                  {w.visible ? <Eye /> : <EyeOff />}
                </Button>
                <Button type="button" size="icon" variant="ghost" aria-label="Configurer le widget" title="Emplacement et paramètres" onClick={() => onOpenChange(id)}>
                  <Settings2 />
                </Button>
                <Button type="button" size="sm" variant="ghost" aria-label="Supprimer le widget" onClick={() => { if (openId === id) onOpenChange(null); onChange(widgets.filter((_, j) => j !== i)); }}>
                  ✕
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
