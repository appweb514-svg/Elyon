"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export type WallFrame = {
  device_id: string;
  name: string;
  serial: string;
  is_preview: boolean;
  status: string;
  computed_status: string;
  player_state: string | null;
  current_media_id: string | null;
  current_media_name: string | null;
  current_media_kind: string | null;
  last_seen_at: string | null;
  screen_id: string | null;
  ticker_text?: string | null;
  ticker_speed?: string | null;
};

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "online") return "success";
  if (status === "pending" || status === "syncing") return "warning";
  if (status === "blocked" || status === "disabled") return "destructive";
  return "secondary";
}

function VncWindow({ frame, delay }: { frame: WallFrame; delay?: number }) {
  const online = frame.computed_status === "online";
  const blanked = frame.player_state === "blank";

  return (
    <article
      className={
        frame.is_preview
          ? "animate-rise overflow-hidden rounded-xl border-2 border-amber-400/80 bg-[#0b1220] shadow-lg shadow-amber-900/20"
          : "animate-rise overflow-hidden rounded-xl border border-slate-700 bg-[#0b1220] shadow-lg"
      }
      style={{ animationDelay: `${delay ?? 0}ms` }}
    >
      <header className="flex items-center gap-2 border-b border-slate-800 bg-gradient-to-b from-slate-800 to-slate-900 px-3 py-2">
        <span className="flex gap-1" aria-hidden>
          <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-slate-100">
            {frame.name}
            <span className="ml-2 font-mono text-[10px] text-slate-400">{frame.serial}</span>
          </p>
        </div>
        <Badge variant={frame.is_preview ? "warning" : statusVariant(frame.computed_status)}>
          {frame.is_preview ? "BROUILLON" : frame.computed_status}
        </Badge>
        <span className="rounded bg-slate-950 px-1.5 py-0.5 font-mono text-[10px] tracking-wide text-sky-400">
          VNC
        </span>
      </header>
      <Link href={`/devices/${frame.device_id}`} className="block">
        <div className="relative aspect-video bg-black">
          {online && frame.player_state !== "playing" && frame.player_state !== "blank" ? (
            <div className="elyon-idle absolute inset-0 flex flex-col items-center justify-center gap-3 overflow-hidden">
              <span className="elyon-idle-orb left-[8%] top-[15%] h-24 w-24 bg-sky-500" />
              <span className="elyon-idle-orb right-[10%] top-[55%] h-32 w-32 bg-indigo-500" style={{ animationDelay: "3s" }} />
              <span className="elyon-idle-orb bottom-[10%] left-[45%] h-20 w-20 bg-cyan-400" style={{ animationDelay: "6s" }} />
              <span className="elyon-idle-text text-lg font-semibold tracking-wide text-slate-100">
                Affichage en préparation
              </span>
              {frame.ticker_text ? (
                <div className="absolute bottom-0 left-0 right-0 overflow-hidden bg-black/70 px-3 py-1.5 text-xs whitespace-nowrap text-slate-100">
                  <span
                    className={`elyon-ticker inline-block ${frame.ticker_speed && frame.ticker_speed !== "normal" ? `elyon-ticker-${frame.ticker_speed}` : ""}`}
                  >
                    {frame.ticker_text}
                  </span>
                </div>
              ) : null}
            </div>
          ) : online ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={`/api/admin/wall/${frame.device_id}/live`}
              alt={frame.current_media_name ?? "écran"}
              className="h-full w-full object-contain"
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-500">
              <span className="text-3xl">{blanked ? "⬛" : "💤"}</span>
              <span className="text-xs">
                {blanked ? "Écran éteint (blank)" : "Hors ligne"}
              </span>
            </div>
          )}
          {frame.is_preview ? (
            <div className="absolute left-2 top-2 rounded bg-amber-500/90 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-950">
              Aperçu admin — modifications non publiées
            </div>
          ) : null}
        </div>
      </Link>
      <footer className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 border-t border-slate-800 px-3 py-1.5 text-[11px] text-slate-400">
        <span className="truncate">
          {frame.current_media_name ?? "aucun média"}
          {frame.player_state ? ` · ${frame.player_state}` : ""}
        </span>
        <span className={online ? "text-emerald-400" : "text-slate-500"}>
          {online ? "● connecté" : "○ déconnecté"}
        </span>
      </footer>
    </article>
  );
}

export default function WallPage() {
  const [frames, setFrames] = useState<WallFrame[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await api.get<WallFrame[]>("/api/admin/wall");
        if (!cancelled) {
          setFrames(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(String((err as Error).message ?? err));
      }
    }
    load();
    const timer = setInterval(load, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (!frames) {
    return <p className="text-sm text-muted-foreground">Connexion au mur d&apos;écrans…</p>;
  }

  const preview = frames.filter((f) => f.is_preview);
  const others = frames.filter((f) => !f.is_preview);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Mur d&apos;écrans</h1>
        <p className="text-sm text-muted-foreground">
          Prévisualisation type VNC de tous les Raspberry Pi. Le cadre ambre est
          l&apos;aperçu administrateur : il joue le planning <strong>courant</strong>{" "}
          sans attendre « Publier ».
        </p>
      </div>
      {preview.length > 0 ? (
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-amber-600">
          Aperçu avant publication
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {preview.map((frame, i) => (
            <VncWindow key={frame.device_id} frame={frame} delay={i * 80} />
          ))}
        </div>
      </section>
      ) : (
        <p className="text-sm text-muted-foreground">
          Aucun Raspberry d&apos;aperçu. Enrôlez un player avec le serial{" "}
          <code>emu-rpi-preview</code> puis marquez-le aperçu.
        </p>
      )}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Players ({others.length})
        </h2>
        {others.length === 0 ? (
          <p className="text-sm text-muted-foreground">Aucun autre appareil.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {others.map((frame, i) => (
              <VncWindow key={frame.device_id} frame={frame} delay={i * 60} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
