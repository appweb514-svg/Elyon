"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
  sha256: string;
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
};
type WidgetFeed = {
  ticker_text: string | null;
  ticker_speed: string | null;
  weather_text: string | null;
  weather_days: string | null;
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

  async function heartbeat(s: Stored, playerState: string, mediaId: string | null): Promise<boolean> {
    try {
      const res = await fetch(`/api/devices/${s.device_id}/heartbeat`, {
        method: "POST",
        headers: { Authorization: `Bearer ${s.token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ state: playerState, current_media_id: mediaId }),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  const runKiosk = useCallback(
    async (s: Stored) => {
      let alive = true;
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

      // Boucle : manifeste → lecture → heartbeat. Simple et robuste.
      const loop = async () => {
        for (;;) {
          if (!alive) return;
          const m = await fetchManifest();
          const items: QueueItem[] = [];
          if (m && m.blocks?.length) {
            const blocks = [...m.blocks].sort((a, b) => b.priority - a.priority);
            for (const entry of blocks[0]?.entries ?? []) {
              items.push({
                media_id: entry.media_id,
                kind: entry.kind,
                name: entry.name,
                duration: entry.duration_seconds ?? null,
                url: entry.url ?? null,
              });
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
            const item = items[i];
            setStatus(`lecture ${item.name}`);
            await heartbeat(s, "playing", item.media_id);
            await playItem(s, item, () => alive);
          }
        }
      };
      void loop();
      return () => {
        alive = false;
        clearInterval(feedTimer);
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
            <div className="absolute left-0 right-0 top-0 z-10 rounded-b-lg bg-black/60 px-4 py-2 text-center text-xl font-medium">
              {idleWeatherText}
              {feed?.weather_days && (
                <span className="block text-sm text-slate-300">{feed.weather_days}</span>
              )}
            </div>
          )}
          <ClockWidget
            widget={idleClock}
            siteTimezone={siteTimezone}
            className="absolute right-6 top-16 z-10 rounded-lg bg-black/60 px-4 py-2 text-3xl font-semibold"
          />
          <span className="elyon-idle-text text-3xl font-semibold tracking-wide">
            Affichage en préparation
          </span>
          {idleTicker && (
            <div className="absolute bottom-0 left-0 right-0 overflow-hidden bg-black/70 px-4 py-2 text-base whitespace-nowrap">
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

/** Lecture d'un item : vidéo native, image ou page web (iframe). */
async function playItem(s: Stored, item: QueueItem, alive: () => boolean): Promise<void> {
  if (item.kind === "web") {
    const target = item.url ?? "";
    if (!target) return;
    await new Promise<void>((resolve) => {
      const iframe = document.createElement("iframe");
      iframe.src = target;
      iframe.title = item.name;
      iframe.className = "absolute inset-0 h-full w-full border-0 bg-white";
      const root = document.getElementById("kiosk-root");
      if (root) {
        root.innerHTML = "";
        root.appendChild(iframe);
      }
      setTimeout(resolve, (item.duration ?? 30) * 1000);
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
      video.onended = () => resolve();
      video.onerror = () => resolve();
      const root = document.getElementById("kiosk-root");
      if (!root) return resolve();
      root.innerHTML = "";
      root.appendChild(video);
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
      setTimeout(resolve, (item.duration ?? 10) * 1000);
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
}: {
  widget: Record<string, unknown> | undefined;
  siteTimezone: string | null;
  className: string;
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
  return <div className={className}>{clock}</div>;
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
    ? feed?.weather_text ??
      `${String(((weather.params ?? {}) as Record<string, unknown>)?.city ?? "Météo")}`
    : null;

  return (
    <div className="absolute inset-0" id="kiosk-root-wrap">
      <div className="absolute inset-0" id="kiosk-root" />
      {status.startsWith("lecture") === false && status !== "lecture" && (
        <div className="elyon-idle absolute inset-0 flex flex-col items-center justify-center gap-4">
          <span className="elyon-idle-orb left-[8%] top-[15%] h-40 w-40 bg-sky-500" />
          <span className="elyon-idle-orb right-[10%] top-[55%] h-56 w-56 bg-indigo-500" style={{ animationDelay: "3s" }} />
          <span className="elyon-idle-orb bottom-[10%] left-[45%] h-32 w-32 bg-cyan-400" style={{ animationDelay: "6s" }} />
          <span className="elyon-idle-text text-3xl font-semibold tracking-wide">Affichage en préparation</span>
        </div>
      )}
      {weatherText && (
        <div className="absolute left-0 right-0 top-0 z-10 rounded-b-lg bg-black/60 px-4 py-2 text-center text-2xl font-medium">
          {weatherText}
          {feed?.weather_days && (
            <span className="block text-sm text-slate-300">{feed.weather_days}</span>
          )}
        </div>
      )}
      <ClockWidget
        widget={clockWidget}
        siteTimezone={siteTimezone}
        className={`absolute right-6 z-10 rounded-lg bg-black/60 px-4 py-2 text-4xl font-semibold ${
          hasWeatherBand ? "top-20" : "top-4"
        }`}
      />
      {centerText && (
        <div className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-xl bg-black/70 px-8 py-4 text-3xl font-semibold">
          {centerText}
        </div>
      )}
      {tickerVal && (
        <div className="absolute bottom-0 left-0 right-0 z-10 overflow-hidden bg-black/70 px-4 py-2 text-xl whitespace-nowrap">
          <span className={`elyon-ticker inline-block ${tickerSpeed(ticker) !== "normal" ? `elyon-ticker-${tickerSpeed(ticker)}` : ""}`}>
            {tickerVal}
          </span>
        </div>
      )}
    </div>
  );
}
