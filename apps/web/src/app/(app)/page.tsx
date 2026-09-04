"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Archive,
  CircleAlert,
  Clock3,
  FileVideo,
  HardDrive,
  MonitorSmartphone,
  Wifi,
} from "lucide-react";

import { api, formatBytes, formatDate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/metric-card";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Dashboard = {
  devices_total: number;
  devices_online: number;
  devices_offline?: number;
  devices_pending: number;
  media_count: number;
  media_ready?: number;
  media_bytes?: number;
  events_24h?: number;
  events_warning_24h?: number;
  recent_events: {
    id: string;
    type: string;
    level: string;
    message: string;
    created_at: string;
  }[];
};

function levelVariant(level: string): "default" | "destructive" | "warning" | "secondary" {
  if (level === "error") return "destructive";
  if (level === "warning") return "warning";
  if (level === "info") return "secondary";
  return "default";
}

const EVENT_ICON: Record<string, string> = {
  device_online: "🟢",
  device_offline: "🔴",
  command_failed: "⚠️",
};

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Dashboard>("/api/dashboard")
      .then(setData)
      .catch((err) => setError(String(err.message ?? err)));
  }, []);

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (!data) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Tableau de bord</h1>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card-shimmer h-28 rounded-xl" />
          ))}
        </div>
        <div className="card-shimmer h-64 rounded-xl" />
      </div>
    );
  }

  const total = data.devices_total || 0;
  const online = data.devices_online || 0;
  const offline = data.devices_offline ?? Math.max(total - online, 0);
  const pending = data.devices_pending || 0;
  const readyRate = data.media_count ? Math.round(((data.media_ready ?? data.media_count) / data.media_count) * 100) : 0;
  const onlineRate = total ? Math.round((online / total) * 100) : 0;

  const segments = [
    { label: "En ligne", value: online, color: "bg-emerald-500" },
    { label: "Hors ligne", value: offline, color: "bg-red-400" },
    { label: "En attente", value: pending, color: "bg-amber-400" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Tableau de bord</h1>
          <p className="text-sm text-muted-foreground">
            {new Date().toLocaleDateString("fr-FR", {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}{" "}
            — vue d&apos;ensemble du parc d&apos;affichage
          </p>
        </div>
        <Badge variant="secondary" className="gap-1.5">
          <span className="h-2 w-2 animate-pulse-dot rounded-full bg-emerald-500" />
          Serveur en ligne
        </Badge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Appareils"
          value={total}
          hint={`${onlineRate}% en ligne`}
          icon={<MonitorSmartphone className="h-5 w-5" />}
          href="/devices"
          delay={0}
        />
        <MetricCard
          label="En ligne"
          value={online}
          hint={`${offline} hors ligne`}
          icon={<Wifi className="h-5 w-5" />}
          href="/devices"
          tone="success"
          delay={60}
        />
        <MetricCard
          label="Médias"
          value={data.media_count}
          hint={readyRate > 0 ? `${readyRate}% prêts à diffuser` : "bibliothèque"}
          icon={<FileVideo className="h-5 w-5" />}
          href="/media"
          tone="accent"
          delay={120}
        />
        <MetricCard
          label="Média en stockage"
          value={Math.round((data.media_bytes ?? 0) / 1024 / 1024)}
          hint={formatBytes(data.media_bytes ?? 0)}
          icon={<HardDrive className="h-5 w-5" />}
          href="/media"
          delay={180}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Derniers événements</CardTitle>
            <CardDescription>Activité récente des appareils et du serveur</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="divide-y">
              {data.recent_events.map((event) => (
                <div
                  key={event.id}
                  className="flex items-center gap-3 py-2.5 transition-colors hover:bg-muted/40"
                >
                  <span className="font-mono text-sm">
                    {EVENT_ICON[event.type] ?? (event.level === "warning" || event.level === "error" ? "⚠️" : "•")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm">{event.message}</p>
                    <p className="text-xs text-muted-foreground">
                      {event.type} · {formatDate(event.created_at)}
                    </p>
                  </div>
                  <Badge variant={levelVariant(event.level)}>{event.level}</Badge>
                </div>
              ))}
              {data.recent_events.length === 0 && (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Aucun événement pour le moment.
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>État des appareils</CardTitle>
              <CardDescription>Statut en temps réel</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex h-3 overflow-hidden rounded-full bg-muted">
                {segments
                  .filter((s) => s.value > 0)
                  .map((s) => (
                    <div
                      key={s.label}
                      className={`${s.color} h-full transition-all duration-700`}
                      style={{ width: `${total ? (s.value / total) * 100 : 0}%` }}
                    />
                  ))}
                {total === 0 && <div className="h-full w-full bg-muted" />}
              </div>
              <ul className="space-y-1.5">
                {segments.map((s) => (
                  <li key={s.label} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <span className={`h-2 w-2 rounded-full ${s.color}`} />
                      {s.label}
                    </span>
                    <span className="font-semibold tabular-nums">{s.value}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Activité 24 h</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border p-3">
                <Clock3 className="h-4 w-4 text-muted-foreground" />
                <p className="mt-2 text-xl font-bold tabular-nums">{data.events_24h ?? 0}</p>
                <p className="text-xs text-muted-foreground">événements</p>
              </div>
              <div className="rounded-lg border p-3">
                <CircleAlert className="h-4 w-4 text-amber-600" />
                <p className="mt-2 text-xl font-bold tabular-nums text-amber-600">
                  {data.events_warning_24h ?? 0}
                </p>
                <p className="text-xs text-muted-foreground">alertes / erreurs</p>
              </div>
            </CardContent>
          </Card>

          <Card className="border-primary/20 bg-gradient-to-br from-primary/5 to-indigo-500/5">
            <CardContent className="flex items-center gap-3 p-4">
              <Archive className="h-8 w-8 text-primary" />
              <div>
                <p className="text-sm font-medium">Bibliothèque média</p>
                <p className="text-xs text-muted-foreground">
                  {data.media_count} médias ({formatBytes(data.media_bytes ?? 0)}) —{" "}
                  <Link href="/media" className="font-medium text-primary underline-offset-4 hover:underline">
                    gérer
                  </Link>
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {pending > 0 && (
        <div className="animate-rise flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <p>
            <strong>{pending}</strong> appareil(s) en attente d&apos;approbation.{" "}
            <Link href="/devices" className="font-medium underline underline-offset-4">
              Revoir les demandes
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
