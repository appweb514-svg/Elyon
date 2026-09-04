"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, formatDate } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type AuditEntry = {
  id: string;
  org_id: string | null;
  user_id: string | null;
  user_name?: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  resource_name?: string | null;
  detail: string | null;
  ip: string | null;
  created_at: string;
};

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    "site.create": "Création de site",
    "site.update": "Modification de site",
    "site.delete": "Suppression de site",
    "screen.create": "Création d'écran",
    "screen.update": "Modification d'écran",
    "screen.delete": "Suppression d'écran",
    "device.create": "Enrôlement d'appareil",
    "device.update": "Modification d'appareil",
    "device.approve": "Approbation d'appareil",
    "device.block": "Blocage d'appareil",
    "device.disable": "Désactivation d'appareil",
    "device.rotate_token": "Rotation de jeton",
    "media.upload": "Envoi de média",
    "media.delete": "Suppression de média",
    "playlist.create": "Création de playlist",
    "playlist.update": "Modification de playlist",
    "playlist.delete": "Suppression de playlist",
    "schedule.create": "Création de planning",
    "schedule.update": "Modification de planning",
    "schedule.delete": "Suppression de planning",
    "manifest.publish": "Publication de manifeste",
    "command.issue": "Commande envoyée",
    "user.create": "Création d'utilisateur",
    "user.update": "Modification d'utilisateur",
    "user.delete": "Suppression d'utilisateur",
    "organization.create": "Création d'organisation",
  };
  return map[action] ?? action;
}

const ACTION_TONE: Record<string, string> = {
  "device.approve": "bg-emerald-100 text-emerald-700",
  "device.block": "bg-red-100 text-red-700",
  "device.delete": "bg-red-100 text-red-700",
  "device.rotate_token": "bg-amber-100 text-amber-700",
  "media.delete": "bg-red-100 text-red-700",
  "schedule.delete": "bg-red-100 text-red-700",
  "manifest.publish": "bg-indigo-100 text-indigo-700",
};

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [filter, setFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState(10);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [names, setNames] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (actionFilter) params.set("action", actionFilter);
      params.set("limit", String(pageSize));
      params.set("offset", String(offset));
      const qs = params.toString();
      const page = await api.get<{ items: AuditEntry[]; total: number }>(
        `/api/audit/logs?${qs}`
      );
      setEntries(page.items);
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [actionFilter, pageSize, offset]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  const filtered = (entries ?? []).filter((e) => {
    if (!filter) return true;
    const needle = filter.toLowerCase();
    return [e.action, e.resource_id, e.detail, e.ip, e.user_id]
      .filter(Boolean)
      .some((v) => String(v).toLowerCase().includes(needle));
  });
  const page = offset / pageSize + 1;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  const actions = Array.from(new Set((entries ?? []).map((e) => e.action))).sort();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Audit</h1>
        <p className="text-sm text-muted-foreground">
          Journal des actions effectuées dans le back-office — rafraîchi toutes les 15 s.
        </p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Journal d&apos;audit</CardTitle>
          <CardDescription>
            Les actions sensibles (enrôlement, publication, suppression, rotation) sont
            tracées avec leur auteur.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="search">Recherche</Label>
              <Input
                id="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filtrer par message, ID ressource, IP…"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="action-type">Action</Label>
              <select
                id="action-type"
                className="flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm shadow-sm"
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
              >
                <option value="">— Toutes —</option>
                {actions.map((a) => (
                  <option key={a} value={a}>
                    {actionLabel(a)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {entries === null ? (
            <div className="card-shimmer h-48 rounded-lg" />
          ) : (
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Horodatage</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Ressource</TableHead>
                    <TableHead>Détail</TableHead>
                    <TableHead>IP</TableHead>
                    <TableHead>Utilisateur</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((entry) => (
                    <TableRow key={entry.id} className="animate-fade-in">
                      <TableCell className="whitespace-nowrap text-xs">
                        {formatDate(entry.created_at)}
                      </TableCell>
                      <TableCell>
                        <span
                          className={`inline-flex rounded-md px-2 py-0.5 text-xs font-semibold ${
                            ACTION_TONE[entry.action] ?? "bg-secondary text-secondary-foreground"
                          }`}
                        >
                          {actionLabel(entry.action)}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs">
                        <span className="text-muted-foreground">{entry.resource_type}</span>
                        {entry.resource_name ? (
                          <span className="ml-1 font-medium">{entry.resource_name}</span>
                        ) : entry.resource_id ? (
                          <span className="ml-1 font-mono text-[10px] text-muted-foreground">
                            {entry.resource_id}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell className="max-w-xs truncate text-xs" title={entry.detail ?? ""}>
                        {entry.detail ?? "—"}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{entry.ip ?? "—"}</TableCell>
                      <TableCell className="text-xs">
                        {entry.user_name ?? (
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {entry.user_id ?? "—"}
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {filtered.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6} className="text-muted-foreground">
                        Aucune entrée d&apos;audit.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm">
              <Label htmlFor="page-size" className="text-xs text-muted-foreground">Lignes par page</Label>
              <select
                id="page-size"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setOffset(0);
                }}
                className="h-8 rounded-md border border-input bg-card px-2 text-sm"
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
              <span className="text-xs text-muted-foreground">
                {total} entrée{total > 1 ? "s" : ""} au total
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <Button
                size="icon"
                variant="outline"
                aria-label="Page précédente"
                disabled={offset <= 0}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
              >
                <ChevronLeft />
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {page} / {pageCount}
              </span>
              <Button
                size="icon"
                variant="outline"
                aria-label="Page suivante"
                disabled={offset + pageSize >= total}
                onClick={() => setOffset(offset + pageSize)}
              >
                <ChevronRight />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
