"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { cn } from "@/lib/utils";

function useCountUp(target: number, durationMs = 900): number {
  const [value, setValue] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (target === 0) {
      setValue(0);
      return;
    }
    let frame: number;
    const step = (ts: number) => {
      if (startRef.current === null) startRef.current = ts;
      const progress = Math.min((ts - startRef.current) / durationMs, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(target * eased));
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs]);

  return value;
}

export function MetricCard({
  label,
  value,
  hint,
  icon,
  href,
  tone = "default",
  delay = 0,
}: {
  label: string;
  value: number;
  hint?: string;
  icon?: React.ReactNode;
  href?: string;
  tone?: "default" | "success" | "warning" | "destructive" | "accent";
  delay?: number;
}) {
  const count = useCountUp(value);

  const toneClasses: Record<string, string> = {
    default: "text-foreground",
    success: "text-emerald-600",
    warning: "text-amber-600",
    destructive: "text-red-600",
    accent: "text-primary",
  };
  const iconClasses: Record<string, string> = {
    default: "bg-primary/10 text-primary",
    success: "bg-emerald-100 text-emerald-700",
    warning: "bg-amber-100 text-amber-700",
    destructive: "bg-red-100 text-red-700",
    accent: "bg-primary/10 text-primary",
  };

  const body = (
    <div
      className="animate-rise group relative overflow-hidden rounded-xl border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/40 to-transparent transition-transform duration-700 ease-out group-hover:translate-x-full"
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p
            className={cn(
              "mt-1.5 text-3xl font-bold tabular-nums tracking-tight",
              toneClasses[tone]
            )}
          >
            {count}
          </p>
          {hint && <p className="mt-1.5 text-xs text-muted-foreground">{hint}</p>}
        </div>
        {icon && (
          <div
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-transform duration-300 group-hover:scale-110",
              iconClasses[tone]
            )}
          >
            {icon}
          </div>
        )}
      </div>
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="block">
        {body}
      </Link>
    );
  }
  return body;
}
