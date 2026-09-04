"use client";

import { cn } from "@/lib/utils";

/**
 * Cadre de télévision : l'aperçu d'écran est présenté dans un dessin de TV
 * (cadre, pied, LED) plutôt qu'un simple rectangle 16:9.
 */
export function TvFrame({
  children,
  className,
  label,
}: {
  children: React.ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <div className={cn("mx-auto w-full max-w-2xl", className)}>
      <div className="rounded-[1.25rem] border-4 border-slate-800 bg-slate-900 p-2 shadow-2xl shadow-slate-950/40 ring-1 ring-slate-700/60">
        <div className="relative aspect-video w-full overflow-hidden rounded-[0.75rem] bg-black">
          {children}
        </div>
        <div className="mt-1.5 flex items-center justify-between px-2">
          <span className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-widest text-slate-500">
            <span
              className={
                "h-1.5 w-1.5 rounded-full " +
                (label === "off" ? "bg-slate-600" : "animate-pulse-dot bg-emerald-500")
              }
            />
            {label === "off" ? "HORS LIGNE" : "EN DIRECT"}
          </span>
          <span className="text-[10px] font-semibold tracking-[0.3em] text-slate-600">
            ELYON
          </span>
        </div>
      </div>
      <div className="mx-auto h-3 w-24 rounded-b-lg bg-slate-800 shadow-lg" />
      <div className="mx-auto h-1.5 w-44 rounded-b-xl bg-slate-700/80" />
    </div>
  );
}
