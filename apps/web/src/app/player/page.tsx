"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

/**
 * Player web universel : fonctionne sur tout appareil doté d'un navigateur
 * (Tizen, webOS, BrightSign, ChromeOS, PC, tablette…).
 *
 * Pairage : code d'enrôlement de site (généré dans Elyon) → device à
 * approuver → kiosque plein écran piloté par le manifeste publié.
 */

const STORE_KEY = "elyon_player_v1";

type Stored = { device_id: string; token: string; serial: string; name: string };

type ManifestMedia = {
  media_id: string;
  name: string;
  kind: string;
  sha256?: string | null;
  page_files?: Array<{ index?: number }> | null;
};
type ManifestEntry = {
  media_id: string;
  name: string;
  kind: string;
  duration_seconds?: number | null;
  url?: string | null;
};
type ManifestBlock = { schedule_id: string; schedule_name: string; priority: number; entries: ManifestEntry[] };
type Manifest = {
  version: string;
  media: ManifestMedia[];
  blocks: ManifestBlock[];
  widgets: Array<Record<string, unknown>> | null;
  site_timezone?: string | null;
};

type QueueItem = {
  media_id: string;
  kind: string;
  name: string;
  duration: number | null;
  url?: string | null;
  page_index?: number | null;
};
type WeatherInfo = {
  city?: string | null;
  temperature?: number | null;
  code?: number | null;
  forecast?: Array<{
    date?: string;
    max?: number | null;
    min?: number | null;
    code?: number | null;
  }>;
};
type WidgetFeed = {
  ticker_text: string | null;
  ticker_speed: string | null;
  weather_text: string | null;
  weather_days: string | null;
  weather?: WeatherInfo | null;
};

function load(): Stored | null {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Stored) : null;
  } catch {
    return null;
  }
}

function deviceFileUrl(deviceId: string, mediaId: string, token: string): string {
  return `/api/media/${mediaId}/device-file?token=${encodeURIComponent(token)}`;
}

export default function PlayerPage() {
  const [stored, setStored] = useState<Stored | null>(null);
  const [booted, setBooted] = useState(false);
  const [pairCode, setPairCode] = useState("");
  const [pairName, setPairName] = useState("");
  const [pairError, setPairError] = useState<string | null>(null);
  const [pendingApproval, setPendingApproval] = useState(false);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [status, setStatus] = useState<string>("initialisation…");
  const [feed, setFeed] = useState<WidgetFeed | null>(null);

  const tokenRef = useRef<Stored | null>(null);

  useEffect(() => {
    const s = load();
    tokenRef.current = s;
    setStored(s);
    setBooted(true);
  }, []);

  const store = useCallback((s: Stored | null) => {
    tokenRef.current = s;
    setStored(s);
    if (s) localStorage.setItem(STORE_KEY, JSON.stringify(s));
    else localStorage.removeItem(STORE_KEY);
  }, []);

  async function pair() {
    setPairError(null);
    const serial = `web-${Math.random().toString(36).slice(2, 10)}`;
    try {
      const res = await fetch("/api/enroll/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          serial,
          name: pairName.trim() || `Web ${serial.slice(-4)}`,
          site_code: pairCode.trim().toUpperCase(),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { device_id: string; token: string };
      store({ device_id: data.device_id, token: data.token, serial, name: pairName.trim() || serial });
      setPendingApproval(true);
      setStatus("En attente d'approbation dans Elyon (Appareils → Approuver)…");
    } catch (err) {
      setPairError(String((err as Error).message ?? err));
    }
  }

  async function heartbeat(
    s: Stored,
    playerState: string,
    mediaId: string | null,
    pageIndex: number | null = null
  ): Promise<boolean> {
    try {
      const res = await fetch(`/api/devices/${s.device_id}/heartbeat`, {
        method: "POST",
        headers: { Authorization: `Bearer ${s.token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ state: playerState, current_media_id: mediaId, page_index: pageIndex }),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  const runKiosk = useCallback(
    async (s: Stored) => {
      let alive = true;
      // Commande « Afficher » en cours (ref pour éviter le narrowing TS).
      const showRef = { current: null as QueueItem | null };
      // Pause pilotée depuis le back-office + vidéo en cours (pour la figer).
      const pausedRef = { current: false };
      const videoRef = { current: null as HTMLVideoElement | null };
      const fetchManifest = async (): Promise<Manifest | null> => {
        try {
          const res = await fetch(`/api/devices/${s.device_id}/manifest`, {
            headers: { Authorization: `Bearer ${s.token}` },
          });
          if (!res.ok) return null;
          return (await res.json()) as Manifest;
        } catch {
          return null;
        }
      };

      // Feed widgets (RSS résolu + météo) toutes les 5 min.
      const fetchFeed = async () => {
        try {
          const res = await fetch(`/api/devices/${s.device_id}/widgets-feed`, {
            headers: { Authorization: `Bearer ${s.token}` },
          });
          if (res.ok) setFeed((await res.json()) as WidgetFeed);
        } catch {
          /* feed indisponible : on garde le précédent */
        }
      };
      void fetchFeed();
      const feedTimer = setInterval(fetchFeed, 5 * 60 * 1000);

      // Commandes serveur (Afficher / Arrêter / Pause) : le polling continue
      // pendant la lecture pour qu'une pause soit immédiate.
      let commandPollBusy = false;
      const checkCommands = async () => {
        if (commandPollBusy) return;
        commandPollBusy = true;
        const commands = await fetchCommands(s);
        for (const command of commands) {
          let commandError: string | null = null;
          try {
            if (command.type === "show") {
              const payload = JSON.parse(command.payload ?? "{}") as Record<string, unknown>;
              const mediaId = String(payload.media_id ?? "");
              const kind = String(payload.kind ?? "image");
              const url = payload.url ? String(payload.url) : null;
              if (!mediaId) {
                commandError = "Commande SHOW sans media_id";
              } else if (kind === "web" && !url) {
                commandError = "Commande SHOW web sans url";
              } else {
                showRef.current = {
                  media_id: mediaId,
                  kind,
                  name: String(payload.name ?? mediaId),
                  duration:
                    payload.duration_seconds != null
                      ? Number(payload.duration_seconds)
                      : null,
                  url,
                };
              }
            } else if (command.type === "stop_show") {
              showRef.current = null;
            } else if (command.type === "pause") {
              pausedRef.current = true;
              videoRef.current?.pause();
            } else if (command.type === "resume") {
              pausedRef.current = false;
              void videoRef.current?.play().catch(() => undefined);
            } else if (command.type === "resync") {
              // Rien à faire : la boucle relit le manifeste juste après.
            } else if (command.type === "reboot") {
              await ackCommand(s, command.id, null);
              window.location.reload();
              return;
            } else {
              commandError = `Commande non supportée par le player web : ${command.type}`;
            }
          } catch {
            commandError = "Commande illisible";
          }
          await ackCommand(s, command.id, commandError);
        }
        commandPollBusy = false;
      };
      const commandTimer = setInterval(() => void checkCommands(), 1000);

      // Boucle : commandes → manifeste → lecture → heartbeat.
      const loop = async () => {
        let currentItem: QueueItem | null = null;
        for (;;) {
          if (!alive) return;
          await checkCommands();
          if (pausedRef.current) {
            await heartbeat(
              s,
              "paused",
              currentItem?.media_id ?? showRef.current?.media_id ?? null,
              currentItem?.page_index ?? null
            );
            await sleep(1_000);
            continue;
          }
          if (showRef.current) {
            const item = showRef.current;
            currentItem = item;
            setStatus(`lecture ${item.name}`);
            await heartbeat(s, "playing", item.media_id, item.page_index ?? null);
            if (item.duration != null) showRef.current = null;
            if (item.kind === "web") {
              await playWeb(item.url ?? "", item.duration ?? 60, () => alive, () => pausedRef.current);
            } else {
              await playItem(s, item, () => alive, () => pausedRef.current, (video) => {
                videoRef.current = video;
              });
            }
            continue;
          }
          const m = await fetchManifest();
          const items: QueueItem[] = [];
          const mediaIndex = new Map((m?.media ?? []).map((media) => [media.media_id, media]));
          if (m && m.blocks?.length) {
            const blocks = [...m.blocks].sort((a, b) => b.priority - a.priority);
            for (const entry of blocks[0]?.entries ?? []) {
              const pages = mediaIndex.get(entry.media_id)?.page_files?.length ?? 1;
              if ((entry.kind === "pdf" || entry.kind === "office") && pages > 1) {
                // Un PDF/Office se déroule page par page (5 s par défaut).
                for (let page = 0; page < pages; page++) {
                  items.push({
                    media_id: entry.media_id,
                    kind: "page",
                    name: `${entry.name} p.${page + 1}`,
                    duration: entry.duration_seconds ?? null,
                    url: null,
                    page_index: page,
                  });
                }
              } else {
                items.push({
                  media_id: entry.media_id,
                  kind: entry.kind,
                  name: entry.name,
                  duration: entry.duration_seconds ?? null,
                  url: entry.url ?? null,
                });
              }
            }
          }
          setManifest(m);
          const approved = await heartbeat(s, items.length ? "playing" : "idle", items[0]?.media_id ?? null);
          if (!approved) {
            setStatus("Appareil non approuvé ou révoqué — en attente…");
            setPendingApproval(true);
            await sleep(5_000);
            continue;
          }
          setPendingApproval(false);
          if (!items.length) {
            setStatus("idle");
            await sleep(5_000);
            continue;
          }
          // Lecture séquentielle (boucle infinie du bloc actif).
          for (let i = 0; i < items.length && alive; i++) {
            await checkCommands();
            if (pausedRef.current || showRef.current) break;
            const item = items[i];
            currentItem = item;
            setStatus(`lecture ${item.name}`);
            await heartbeat(s, "playing", item.media_id, item.page_index ?? null);
            await playItem(s, item, () => alive, () => pausedRef.current, (video) => {
              videoRef.current = video;
            });
          }
        }
      };
      void loop();
      return () => {
        alive = false;
        clearInterval(feedTimer);
        clearInterval(commandTimer);
      };
    },
    [],
  );

  useEffect(() => {
    if (!booted || !stored) return;
    let cleanup: (() => void) | undefined;
    void runKiosk(stored).then((fn) => {
      cleanup = fn;
    });
    return () => cleanup?.();
  }, [booted, stored, runKiosk]);

  if (!booted) return null;

  const widgets = manifest?.widgets ?? [];
  const siteTimezone = manifest?.site_timezone ?? null;
  const ticker = widgets.find((w) => w.position === "bottom-ticker");
  const idleTicker =
    ticker && String(ticker.type) === "rss" ? feed?.ticker_text ?? "" : tickerText(ticker);
  const idleWeather = widgets.find((w) => w.position === "top-band");
  const idleClock = widgets.find((w) => w.position === "top-right");
  const idleWeatherText = idleWeather
    ? feed?.weather_text ?? `${String(((idleWeather.params ?? {}) as Record<string, unknown>)?.city ?? "Météo")}`
    : null;
  const idleWeatherLine = feed?.weather
    ? `${weatherGlyph(feed.weather.code)} ${feed.weather.city ?? "Météo"} · ${Math.round(feed.weather.temperature ?? 0)}°C`
    : idleWeatherText;
  const idleWeatherDays = weatherDaysText(feed?.weather) ?? feed?.weather_days ?? null;

  return (
    <div className="fixed inset-0 bg-black text-white" style={{ overflow: "hidden" }}>
      {/* Kiosque */}
      {stored && !pendingApproval && (
        <KioskScreen status={status} widgets={widgets} feed={feed} siteTimezone={siteTimezone} />
      )}

      {/* Écran d'attente */}
      {(!stored || pendingApproval) && (
        <div className="elyon-idle absolute inset-0 flex flex-col items-center justify-center gap-4">
          <span className="elyon-idle-orb left-[8%] top-[15%] h-40 w-40 bg-sky-500" />
          <span className="elyon-idle-orb right-[10%] top-[55%] h-56 w-56 bg-indigo-500" style={{ animationDelay: "3s" }} />
          <span className="elyon-idle-orb bottom-[10%] left-[45%] h-32 w-32 bg-cyan-400" style={{ animationDelay: "6s" }} />
          {idleWeatherText && (
            <div
              className="absolute left-0 right-0 top-0 z-10 rounded-b-lg bg-black/45 text-center font-medium"
              style={{ ...widgetFont(idleWeather, 14, 160), padding: "0.7vh 1vw" }}
            >
              {idleWeatherLine}
              {idleWeatherDays && (
                <span className="block text-slate-300" style={{ fontSize: "0.55em" }}>
                  {idleWeatherDays}
                </span>
              )}
            </div>
          )}
          <ClockWidget
            widget={idleClock}
            siteTimezone={siteTimezone}
            className="absolute right-[1.5vw] top-[9vh] z-10 rounded-lg bg-black/45 font-semibold"
            style={{ ...widgetFont(idleClock, 16, 180), padding: "0.7vh 1vw" }}
          />
          <span
            className="elyon-idle-text font-semibold tracking-wide"
            style={{ fontSize: "clamp(1.2rem, 4vh, 4rem)" }}
          >
            Affichage en préparation
          </span>
          {idleTicker && (
            <div
              className="absolute bottom-0 left-0 right-0 overflow-hidden bg-black/55 whitespace-nowrap"
              style={{ ...widgetFont(ticker, 12, 140), padding: "0.7vh 1vw" }}
            >
              <span
                className={`elyon-ticker inline-block ${(tickerSpeed(ticker) || feed?.ticker_speed || "normal") !== "normal" ? `elyon-ticker-${tickerSpeed(ticker) || feed?.ticker_speed}` : ""}`}
              >
                {idleTicker}
              </span>
            </div>
          )}
          {!stored && (
            <div className="z-10 mt-6 w-80 rounded-xl bg-slate-900/80 p-5 text-sm shadow-xl">
              <p className="mb-3 font-semibold">Pairer cet écran</p>
              <input
                className="mb-2 w-full rounded-md bg-slate-800 px-3 py-2 outline-none"
                placeholder="Code du site (ex. 7DF6D2)"
                aria-label="Code du site"
                value={pairCode}
                maxLength={8}
                onChange={(e) => setPairCode(e.target.value)}
              />
              <input
                className="mb-3 w-full rounded-md bg-slate-800 px-3 py-2 outline-none"
                placeholder="Nom de l'écran (optionnel)"
                aria-label="Nom de l'écran (optionnel)"
                value={pairName}
                onChange={(e) => setPairName(e.target.value)}
              />
              <button
                className="w-full rounded-md bg-indigo-600 px-3 py-2 font-medium hover:bg-indigo-500 disabled:opacity-50"
                disabled={pairCode.trim().length < 6}
                onClick={() => void pair()}
              >
                Pairer
              </button>
              {pairError && <p className="mt-2 text-xs text-red-400">{pairError}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

type DeviceCommand = { id: string; type: string; payload?: string | null };

async function fetchCommands(s: Stored): Promise<DeviceCommand[]> {
  try {
    const res = await fetch(`/api/devices/${s.device_id}/commands`, {
      headers: { Authorization: `Bearer ${s.token}` },
    });
    if (!res.ok) return [];
    return (await res.json()) as DeviceCommand[];
  } catch {
    return [];
  }
}

async function ackCommand(s: Stored, commandId: string, error: string | null): Promise<void> {
  try {
    await fetch(`/api/devices/${s.device_id}/commands/${commandId}/ack`, {
      method: "POST",
      headers: { Authorization: `Bearer ${s.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ error }),
    });
  } catch {
    /* l'ack sera retenté au prochain passage */
  }
}

/** Attente qui se gèle tant que la pause est active (250 ms par pas). */
async function waitWithPause(
  seconds: number,
  paused: () => boolean,
  alive: () => boolean
): Promise<void> {
  let remaining = Math.max(1, seconds) * 1000;
  while (remaining > 0 && alive()) {
    if (paused()) {
      await sleep(200);
      continue;
    }
    const step = Math.min(250, remaining);
    await sleep(step);
    remaining -= step;
  }
}

/** Affiche une page web dans le kiosque pendant `seconds`. */
async function playWeb(
  target: string,
  seconds: number,
  alive: () => boolean,
  paused: () => boolean
): Promise<void> {
  if (!target || !alive()) return;
  const iframe = document.createElement("iframe");
  iframe.src = target;
  iframe.title = target;
  iframe.className = "absolute inset-0 h-full w-full border-0 bg-white";
  const root = document.getElementById("kiosk-root");
  if (root) {
    root.innerHTML = "";
    root.appendChild(iframe);
  }
  await waitWithPause(seconds, paused, alive);
}

const FR_DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"];

/** Code WMO → glyphe météo (mêmes glyphes que l'aperçu serveur). */
function weatherGlyph(code?: number | null): string {
  if (code == null) return "\u2601";
  const value = Number(code);
  if (value === 0) return "\u2600";
  if (value <= 3) return "\u2601";
  if (value === 45 || value === 48) return "\u2630";
  if ((value >= 51 && value <= 67) || (value >= 80 && value <= 82)) return "\u2614";
  if ((value >= 71 && value <= 77) || value === 85 || value === 86) return "\u2744";
  if (value >= 95) return "\u26a1";
  return "\u2601";
}

function dayLabel(dateStr: string | undefined, index: number): string {
  if (!dateStr) return FR_DAYS[index % 7];
  const date = new Date(`${dateStr.slice(0, 10)}T12:00:00`);
  return Number.isNaN(date.getTime()) ? FR_DAYS[index % 7] : FR_DAYS[(date.getDay() + 6) % 7];
}

/** Ligne de prévision avec icône par jour (ex. « sun mar 21°/12° »). */
function weatherDaysText(info: WeatherInfo | null | undefined): string | null {
  const days = (info?.forecast ?? [])
    .filter((f) => typeof f.max === "number" && typeof f.min === "number")
    .slice(0, 4);
  if (days.length === 0) return null;
  return days
    .map(
      (f, index) =>
        `${weatherGlyph(f.code)} ${dayLabel(f.date, index)} ${Math.round(f.max!)}°/${Math.round(f.min!)}°`
    )
    .join("  ");
}

/** Facteur de taille (identique au player Python : petit/moyen/grand). */
function widgetScale(widget: Record<string, unknown> | undefined): number {
  const params = (widget?.params ?? {}) as Record<string, unknown>;
  const size = String(params.size ?? "medium");
  if (size === "small") return 1;
  if (size === "large") return 2.2;
  return 1.5;
}

/** Taille de police fluide : proportionnelle à la hauteur de l'écran. */
function widgetFont(
  widget: Record<string, unknown> | undefined,
  min: number,
  max: number
): CSSProperties {
  const vh = ((100 / 36) * widgetScale(widget)).toFixed(2);
  return { fontSize: `clamp(${min}px, ${vh}vh, ${max}px)` };
}

function tickerText(w: Record<string, unknown> | undefined): string {
  if (!w) return "";
  const p = (w.params ?? {}) as Record<string, unknown>;
  return String(p.text ?? "");
}

function tickerSpeed(w: Record<string, unknown> | undefined): string {
  if (!w) return "";
  const p = (w.params ?? {}) as Record<string, unknown>;
  return String(p.speed ?? "normal");
}

/** Lecture d'un item : vidéo, image, page PDF/Office ou page web (iframe). */
async function playItem(
  s: Stored,
  item: QueueItem,
  alive: () => boolean,
  paused: () => boolean,
  onVideo?: (video: HTMLVideoElement | null) => void
): Promise<void> {
  if (item.kind === "web") {
    await playWeb(item.url ?? "", item.duration ?? 30, alive, paused);
    return;
  }
  if (item.kind === "page" || item.kind === "pdf" || item.kind === "office") {
    // Page d'un PDF/Office : une page toutes les 5 s (surchargeable).
    const pageIndex = item.page_index ?? 0;
    const pageUrl = `/api/media/${item.media_id}/pages/${pageIndex}/device-file?token=${encodeURIComponent(s.token)}`;
    await new Promise<void>((resolve) => {
      const img = new Image();
      img.className = "absolute inset-0 h-full w-full object-contain";
      img.onload = () => {
        const root = document.getElementById("kiosk-root");
        if (root) {
          root.innerHTML = "";
          root.appendChild(img);
        }
        void waitWithPause(item.duration ?? 5, paused, alive).then(resolve);
      };
      img.onerror = () => setTimeout(resolve, 2_000);
      img.src = pageUrl;
    });
    return;
  }
  const url = deviceFileUrl(s.device_id, item.media_id, s.token);
  if (item.kind === "video") {
    await new Promise<void>((resolve) => {
      const video = document.createElement("video");
      video.src = url;
      video.className = "absolute inset-0 h-full w-full object-contain";
      video.autoplay = true;
      video.onended = () => {
        onVideo?.(null);
        resolve();
      };
      video.onerror = () => {
        onVideo?.(null);
        resolve();
      };
      const root = document.getElementById("kiosk-root");
      if (!root) return resolve();
      root.innerHTML = "";
      root.appendChild(video);
      onVideo?.(video);
      video.play().catch(() => resolve());
    });
    return;
  }
  await new Promise<void>((resolve) => {
    const img = new Image();
    img.className = "absolute inset-0 h-full w-full object-contain";
    img.onload = () => {
      const root = document.getElementById("kiosk-root");
      if (root) {
        root.innerHTML = "";
        root.appendChild(img);
      }
      void waitWithPause(item.duration ?? 10, paused, alive).then(resolve);
    };
    img.onerror = () => setTimeout(resolve, 2_000);
    img.src = url;
  });
  void alive;
}

function formatClock(
  date: Date,
  format: string,
  tzMode: string,
  siteTimezone: string | null
): string {
  const hasSeconds = format === "HH:MM:SS";
  if (tzMode === "utc" || siteTimezone) {
    try {
      const parts = new Intl.DateTimeFormat("fr-FR", {
        hour: "2-digit",
        minute: "2-digit",
        ...(hasSeconds ? { second: "2-digit" } : {}),
        hour12: false,
        timeZone: tzMode === "utc" ? "UTC" : siteTimezone ?? "UTC",
      }).formatToParts(date);
      const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
      const hour = get("hour") === "24" ? "00" : get("hour");
      return hasSeconds
        ? `${hour}:${get("minute")}:${get("second")}`
        : `${hour}:${get("minute")}`;
    } catch {
      // Fuseau inconnu du navigateur : on retombe sur l'heure locale.
    }
  }
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return hasSeconds ? `${hh}:${mm}:${ss}` : `${hh}:${mm}`;
}

/** Horloge de widget : heure du site (fuseau du manifeste) ou UTC. */
function ClockWidget({
  widget,
  siteTimezone,
  className,
  style,
}: {
  widget: Record<string, unknown> | undefined;
  siteTimezone: string | null;
  className: string;
  style?: CSSProperties;
}) {
  const [clock, setClock] = useState("");
  const format = String(((widget?.params ?? {}) as Record<string, unknown>)?.format ?? "HH:MM");
  const tzMode = String(((widget?.params ?? {}) as Record<string, unknown>)?.tz ?? "site");
  useEffect(() => {
    if (!widget) {
      setClock("");
      return;
    }
    const tick = () => setClock(formatClock(new Date(), format, tzMode, siteTimezone));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [widget, format, tzMode, siteTimezone]);
  if (!widget || !clock) return null;
  return (
    <div className={className} style={style}>
      {clock}
    </div>
  );
}

function KioskScreen({
  status,
  widgets,
  feed,
  siteTimezone,
}: {
  status: string;
  widgets: Array<Record<string, unknown>>;
  feed: WidgetFeed | null;
  siteTimezone: string | null;
}) {
  const ticker = widgets.find((x) => x.position === "bottom-ticker");
  const weather = widgets.find((x) => x.position === "top-band");
  const center = widgets.find((x) => x.position === "center");
  const clockWidget = widgets.find((x) => x.position === "top-right");
  const hasWeatherBand = weather !== undefined;
  const centerText = String(((center?.params ?? {}) as Record<string, unknown>)?.text ?? "");
  const tickerVal =
    ticker && String(ticker.type) === "rss" ? feed?.ticker_text ?? "" : tickerText(ticker);
  const weatherText = weather
    ? feed?.weather
      ? `${weatherGlyph(feed.weather.code)} ${feed.weather.city ?? "Météo"} · ${Math.round(feed.weather.temperature ?? 0)}°C`
      : feed?.weather_text ??
        `${String(((weather.params ?? {}) as Record<string, unknown>)?.city ?? "Météo")}`
    : null;
  const weatherDays = weatherDaysText(feed?.weather) ?? feed?.weather_days ?? null;

  return (
    <div className="absolute inset-0" id="kiosk-root-wrap">
      <div className="absolute inset-0" id="kiosk-root" />
      {status.startsWith("lecture") === false && status !== "lecture" && (
        <div className="elyon-idle absolute inset-0 flex flex-col items-center justify-center gap-4">
          <span className="elyon-idle-orb left-[8%] top-[15%] h-40 w-40 bg-sky-500" />
          <span className="elyon-idle-orb right-[10%] top-[55%] h-56 w-56 bg-indigo-500" style={{ animationDelay: "3s" }} />
          <span className="elyon-idle-orb bottom-[10%] left-[45%] h-32 w-32 bg-cyan-400" style={{ animationDelay: "6s" }} />
          <span
            className="elyon-idle-text font-semibold tracking-wide"
            style={{ fontSize: "clamp(1.2rem, 4vh, 4rem)" }}
          >
            Affichage en préparation
          </span>
        </div>
      )}
      {weatherText && (
        <div
          className="absolute left-0 right-0 top-0 z-10 rounded-b-lg bg-black/45 text-center font-medium"
          style={{ ...widgetFont(weather, 14, 160), padding: "0.7vh 1vw" }}
        >
          {weatherText}
          {weatherDays && (
            <span className="block text-slate-300" style={{ fontSize: "0.55em" }}>
              {weatherDays}
            </span>
          )}
        </div>
      )}
      <ClockWidget
        widget={clockWidget}
        siteTimezone={siteTimezone}
        className={`absolute right-[1.5vw] z-10 rounded-lg bg-black/45 font-semibold ${
          hasWeatherBand ? "top-[9vh]" : "top-[2vh]"
        }`}
        style={{ ...widgetFont(clockWidget, 16, 180), padding: "0.7vh 1vw" }}
      />
      {centerText && (
        <div
          className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-xl bg-black/45 text-center font-semibold"
          style={{
            ...widgetFont(center, 14, 160),
            padding: "1vh 1.4vw",
            maxWidth: "92vw",
          }}
        >
          {centerText}
        </div>
      )}
      {tickerVal && (
        <div
          className="absolute bottom-0 left-0 right-0 z-10 overflow-hidden bg-black/55 whitespace-nowrap"
          style={{ ...widgetFont(ticker, 12, 140), padding: "0.7vh 1vw" }}
        >
          <span className={`elyon-ticker inline-block ${tickerSpeed(ticker) !== "normal" ? `elyon-ticker-${tickerSpeed(ticker)}` : ""}`}>
            {tickerVal}
          </span>
        </div>
      )}
    </div>
  );
}
