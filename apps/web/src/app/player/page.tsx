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
type ManifestEntry = { media_id: string; name: string; kind: string; duration_seconds?: number | null };
type ManifestBlock = { schedule_id: string; schedule_name: string; priority: number; entries: ManifestEntry[] };
type Manifest = {
  version: string;
  media: ManifestMedia[];
  blocks: ManifestBlock[];
  widgets: Array<Record<string, unknown>> | null;
};

type QueueItem = { media_id: string; kind: string; name: string; duration: number | null };

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
        body: JSON.stringify({ player_state: playerState, current_media_id: mediaId }),
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
  const ticker = widgets.find((w) => w.position === "bottom-ticker");
  const center = widgets.find((w) => w.position === "center");
  const clock = widgets.find((w) => w.position === "top-right");

  return (
    <div className="fixed inset-0 bg-black text-white" style={{ overflow: "hidden" }}>
      {/* Kiosque */}
      {stored && !pendingApproval && <KioskScreen stored={stored} status={status} widgets={widgets} />}

      {/* Écran d'attente */}
      {(!stored || pendingApproval) && (
        <div className="elyon-idle absolute inset-0 flex flex-col items-center justify-center gap-4">
          <span className="elyon-idle-orb left-[8%] top-[15%] h-40 w-40 bg-sky-500" />
          <span className="elyon-idle-orb right-[10%] top-[55%] h-56 w-56 bg-indigo-500" style={{ animationDelay: "3s" }} />
          <span className="elyon-idle-orb bottom-[10%] left-[45%] h-32 w-32 bg-cyan-400" style={{ animationDelay: "6s" }} />
          <span className="elyon-idle-text text-3xl font-semibold tracking-wide">
            Affichage en préparation
          </span>
          {tickerText(ticker) && (
            <div className="absolute bottom-0 left-0 right-0 overflow-hidden bg-black/70 px-4 py-2 text-base whitespace-nowrap">
              <span
                className={`elyon-ticker inline-block ${tickerSpeed(ticker) ? `elyon-ticker-${tickerSpeed(ticker)}` : ""}`}
              >
                {tickerText(ticker)}
              </span>
            </div>
          )}
          {!stored && (
            <div className="z-10 mt-6 w-80 rounded-xl bg-slate-900/80 p-5 text-sm shadow-xl">
              <p className="mb-3 font-semibold">Pairer cet écran</p>
              <input
                className="mb-2 w-full rounded-md bg-slate-800 px-3 py-2 outline-none"
                placeholder="Code du site (ex. 7DF6D2)"
                value={pairCode}
                maxLength={8}
                onChange={(e) => setPairCode(e.target.value)}
              />
              <input
                className="mb-3 w-full rounded-md bg-slate-800 px-3 py-2 outline-none"
                placeholder="Nom de l'écran (optionnel)"
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

/** Lecture d'un item : vidéo native ou image (durée fixe ou 10 s par défaut). */
async function playItem(s: Stored, item: QueueItem, alive: () => boolean): Promise<void> {
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

function KioskScreen({
  stored,
  status,
  widgets,
}: {
  stored: Stored;
  status: string;
  widgets: Array<Record<string, unknown>>;
}) {
  const [clock, setClock] = useState("");
  useEffect(() => {
    const w = widgets.find((x) => x.position === "top-right");
    if (!w) return;
    const fmt = String((w.params as Record<string, unknown>)?.format ?? "HH:MM");
    const tick = () => {
      const d = new Date();
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      const ss = String(d.getSeconds()).padStart(2, "0");
      setClock(fmt === "HH:MM:SS" ? `${hh}:${mm}:${ss}` : `${hh}:${mm}`);
    };
    tick();
    const h = setInterval(tick, 1000);
    return () => clearInterval(h);
  }, [widgets]);

  const ticker = widgets.find((x) => x.position === "bottom-ticker");
  const center = widgets.find((x) => x.position === "center");
  const hasClock = widgets.some((x) => x.position === "top-right");
  const centerText = String(((center?.params ?? {}) as Record<string, unknown>)?.text ?? "");
  const tickerVal = tickerText(ticker);

  return (
    <div className="absolute inset-0" id="kiosk-root-wrap">
      <div className="absolute inset-0" id="kiosk-root" />
      {status.startsWith("lecture") === false && status !== "lecture" && (
        <div className="elyon-idle absolute inset-0 flex flex-col items-center justify-center gap-4">
          <span className="elyon-idle-orb left-[8%] top-[15%] h-40 w-40 bg-sky-500" />
          <span className="elyon-idle-orb right-[10%] top-[55%] h-56 w-56 bg-indigo-500" style={{ animationDelay: "3s" }} />
          <span className="elyon-idle-text text-3xl font-semibold tracking-wide">Affichage en préparation</span>
        </div>
      )}
      {hasClock && clock && (
        <div className="elyon-idle-none absolute right-6 top-4 z-10 rounded-lg bg-black/60 px-4 py-2 text-4xl font-semibold">
          {clock}
        </div>
      )}
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
