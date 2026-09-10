"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Eye, EyeOff, Rss, Settings2, CloudSun, Type, Clock3, MoveHorizontal, X } from "lucide-react";

export type Widget = {
  id?: string;
  type: string; // weather | rss | ticker | text | clock
  position: string; // fixe par type : top-band | top-right | center | bottom-ticker
  visible: boolean;
  locked?: boolean;
  params: Record<string, string | number | null>;
};

/** Emplacement fixe par type de widget. */
const FIXED_POSITION: Record<string, string> = {
  weather: "top-band",
  clock: "top-right",
  rss: "bottom-ticker",
  ticker: "bottom-ticker",
  text: "center",
};

const TYPE_META: Record<string, { label: string; icon: typeof CloudSun; hint: string }> = {
  weather: { label: "Météo", icon: CloudSun, hint: "bandeau en haut" },
  rss: { label: "Flux RSS", icon: Rss, hint: "bandeau défilant en bas" },
  ticker: { label: "Texte déroulant", icon: MoveHorizontal, hint: "bandeau défilant en bas" },
  text: { label: "Texte libre", icon: Type, hint: "au milieu de l'écran" },
  clock: { label: "Horloge", icon: Clock3, hint: "en haut à droite" },
};

/** Nombre maximum de widgets par écran (les barres comptent dedans). */
const MAX_WIDGETS = 3;

/** Taille du widget : grandit le texte (rendu player + aperçu serveur). */
const SIZES = [
  { value: "small", label: "Petit" },
  { value: "medium", label: "Moyen" },
  { value: "large", label: "Grand" },
];

function defaultParams(type: string): Record<string, string | number | null> {
  switch (type) {
    case "weather":
      return { city: "Paris", size: "medium" };
    case "rss":
      return { url: "", size: "medium" };
    case "ticker":
      return { text: "Votre message défilant ici", speed: "normal", size: "medium" };
    case "text":
      return { text: "Votre message ici", size: "medium" };
    case "clock":
      return { format: "HH:MM", size: "medium" };
    default:
      return { size: "medium" };
  }
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

/** Barre de widgets : liste + configuration dépliable sous chaque widget.
 *
 * Emplacements fixes par type (météo en bandeau haut, horloge en haut à
 * droite, texte au centre, RSS/texte déroulant en bas) — pas d'aperçu, pas
 * de déplacement. Taille petit/moyen/grand.
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

  function add(type: string) {
    if (widgets.length >= 3) return;
    const meta = TYPE_META[type];
    if (!meta) return;
    const w: Widget = {
      type,
      position: FIXED_POSITION[type] ?? "bottom-left",
      locked: true,
      visible: true,
      params: defaultParams(type),
    };
    onChange([...widgets, w]);
    onOpenChange(w.id ?? String(widgets.length));
  }

  function update(index: number, patch: Partial<Widget>) {
    const next = widgets.map((w, i) => (i === index ? { ...w, ...patch } : w));
    onChange(next);
  }

  // --- Barres d'information (haut : météo + heure, bas : RSS/texte déroulant) ---

  function findBar(type: string): Widget | undefined {
    return widgets.find((w) => w.type === type && w.visible);
  }

  const topBarEnabled = findBar("weather") !== undefined || findBar("clock") !== undefined;
  const bottomBarEnabled = findBar("rss") !== undefined || findBar("ticker") !== undefined;
  const atLimit = widgets.length >= MAX_WIDGETS;

  /** Active/désactive une barre en conservant les paramètres des widgets. */
  function upsertBar(types: string[], defaults: Widget[], enable: boolean) {
    const existing = widgets.filter((w) => types.includes(w.type));
    if (existing.length > 0) {
      // Les widgets restent dans la liste (masqués) : ville, format, texte…
      // ne sont pas perdus quand on éteint puis rallume la barre.
      onChange(
        widgets.map((w) => (types.includes(w.type) ? { ...w, visible: enable } : w))
      );
      return;
    }
    if (!enable) return;
    const missing = defaults.filter((d) => !widgets.some((w) => w.type === d.type));
    if (widgets.length + missing.length > MAX_WIDGETS) return;
    onChange([...widgets, ...missing]);
  }

  function toggleTopBar(enable: boolean) {
    upsertBar(
      ["weather", "clock"],
      [
        { type: "weather", position: "top-band", locked: true, visible: true, params: defaultParams("weather") },
        { type: "clock", position: "top-right", locked: true, visible: true, params: defaultParams("clock") },
      ],
      enable
    );
  }

  function toggleBottomBar(enable: boolean) {
    upsertBar(
      ["rss", "ticker"],
      [
        { type: "rss", position: "bottom-ticker", locked: true, visible: true, params: defaultParams("rss") },
      ],
      enable
    );
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

  /** Panneau de configuration déployé sous la ligne du widget. */
  function renderConfigPanel(w: Widget, index: number) {
    return (
      <div className="mt-3 space-y-3 rounded-lg border bg-muted/30 p-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Configuration</p>
            <p className="text-xs text-muted-foreground">
              Emplacement fixe : {TYPE_META[w.type]?.hint ?? w.position}.
            </p>
          </div>
          <Button type="button" size="icon" variant="ghost" onClick={() => onOpenChange(null)} aria-label="Fermer">
            <X />
          </Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">Taille</Label>
            <Select value={String(w.params.size ?? "medium")} onChange={(e) => update(index, { params: { ...w.params, size: e.target.value } })}>
              {SIZES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
          </div>
          {w.type === "weather" && (
            <div className="space-y-1">
              <Label className="text-xs">Ville</Label>
              <div className="flex gap-1">
                <Input
                  value={String(w.params.city ?? "")}
                  onChange={(e) => {
                    update(index, { params: { ...w.params, city: e.target.value } });
                    setPreview((p) => {
                      const next = { ...p };
                      delete next[`w${index}`];
                      return next;
                    });
                  }}
                  placeholder="Paris"
                />
                <Button type="button" size="sm" variant="outline" onClick={() => previewWeather(index, String(w.params.city ?? ""))}>Tester</Button>
              </div>
              {loading === `w${index}` && <p className="text-xs text-muted-foreground">Interrogation…</p>}
              <div aria-live="polite">
              {preview[`w${index}`] != null &&
                (() => {
                  const data = preview[`w${index}`] as {
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
            </div>
          )}
          {w.type === "rss" && (
            <div className="space-y-1 sm:col-span-1">
              <Label className="text-xs">URL du flux RSS</Label>
              <Input value={String(w.params.url ?? "")} onChange={(e) => update(index, { params: { ...w.params, url: e.target.value } })} placeholder="https://exemple.fr/rss.xml" />
            </div>
          )}
          {w.type === "ticker" && (
            <>
              <div className="space-y-1 sm:col-span-2">
                <Label className="text-xs">Texte défilant</Label>
                <Input value={String(w.params.text ?? "")} onChange={(e) => update(index, { params: { ...w.params, text: e.target.value } })} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Vitesse de défilement</Label>
                <Select value={String(w.params.speed ?? "normal")} onChange={(e) => update(index, { params: { ...w.params, speed: e.target.value } })}>
                  <option value="slow">Lente</option>
                  <option value="normal">Normale</option>
                  <option value="fast">Rapide</option>
                </Select>
              </div>
            </>
          )}
          {w.type === "text" && (
            <div className="space-y-1 sm:col-span-2">
              <Label className="text-xs">Texte à afficher</Label>
              <Input value={String(w.params.text ?? "")} onChange={(e) => update(index, { params: { ...w.params, text: e.target.value } })} />
            </div>
          )}
          {w.type === "clock" && (
            <>
              <div className="space-y-1">
                <Label className="text-xs">Format</Label>
                <Select value={String(w.params.format ?? "HH:MM")} onChange={(e) => update(index, { params: { ...w.params, format: e.target.value } })}>
                  <option value="HH:MM">Heure:Minute</option>
                  <option value="HH:MM:SS">Heure:Minute:Seconde</option>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Fuseau horaire</Label>
                <Select value={String(w.params.tz ?? "site")} onChange={(e) => update(index, { params: { ...w.params, tz: e.target.value } })}>
                  <option value="site">Heure du site</option>
                  <option value="utc">UTC</option>
                </Select>
              </div>
            </>
          )}
        </div>
        <div className="flex justify-end">
          <Button type="button" onClick={() => onOpenChange(null)}>Terminer</Button>
        </div>
      </div>
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
          Bandeau du haut : météo + horloge {topBarEnabled ? "✓" : ""}
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={bottomBarEnabled}
          data-testid="bottom-bar-toggle"
          onClick={() => toggleBottomBar(!bottomBarEnabled)}
          className={`rounded-md border px-3 py-1.5 text-xs font-medium transition ${bottomBarEnabled ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted/60"}`}
        >
          Bandeau du bas : flux RSS défilant {bottomBarEnabled ? "✓" : ""}
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
            <Button
              key={type}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => add(type)}
              title={atLimit ? "Maximum de 3 widgets atteint" : meta.hint}
              disabled={atLimit}
            >
              <Icon /> {meta.label}
            </Button>
          );
        })}
        <span className="text-xs text-muted-foreground" aria-live="polite">
          Emplacements fixes. Cliquez sur ⚙ pour configurer (taille petit/moyen/grand,{" "}
          {widgets.length}/{MAX_WIDGETS} widgets).
        </span>
      </div>

      {renderBarToggles()}

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
                  <span className="ml-2 text-xs font-normal text-muted-foreground">{meta.hint}</span>
                </button>
                <Button type="button" size="icon" variant="ghost" aria-label={w.visible ? "Cacher le widget" : "Afficher le widget"} title={w.visible ? "Cacher" : "Afficher"} onClick={() => update(i, { visible: !w.visible })}>
                  {w.visible ? <Eye /> : <EyeOff />}
                </Button>
                <Button type="button" size="icon" variant="ghost" aria-label="Configurer le widget" title="Paramètres" onClick={() => onOpenChange(id)}>
                  <Settings2 />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label="Supprimer le widget"
                  title="Supprimer"
                  onClick={() => {
                    if (openId === id) onOpenChange(null);
                    onChange(widgets.filter((_, j) => j !== i));
                  }}
                >
                  <X />
                </Button>
              </div>
              {openId === id && renderConfigPanel(w, i)}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
