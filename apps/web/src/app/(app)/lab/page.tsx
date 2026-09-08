"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";

type Player = {
  serial: string;
  code_file_present: boolean;
  enrolled: boolean;
  device_id: string | null;
  device_name: string | null;
  device_status: string | null;
};

type LabStatus = {
  enroll_dir: string;
  enroll_dir_writable: boolean;
  players: Player[];
};

type InstallResult = {
  org: string;
  site: string;
  codes: Record<string, string>;
  expires_at: string;
  code_files: string[];
};

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente d'approbation",
  approved: "Approuvé (jamais connecté)",
  online: "En ligne",
  offline: "Hors ligne",
  blocked: "Bloqué",
  disabled: "Désactivé",
  maintenance: "Maintenance",
};

export default function LabPage() {
  const [status, setStatus] = useState<LabStatus | null>(null);
  const [result, setResult] = useState<InstallResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.get<LabStatus>("/api/admin/lab/status"));
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    load();
    const h = setInterval(load, 5000);
    return () => clearInterval(h);
  }, [load]);

  async function install() {
    setBusy(true);
    try {
      setResult(await api.post<InstallResult>("/api/admin/lab/install", {}));
      setError(null);
      await load();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Raspberry Pi émulés</h1>
        <p className="text-sm text-muted-foreground">
          Installe et supervise les écrans de labo (players Debian émulés, rendu
          dummy) sans matériel.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Installation</CardTitle>
          <CardDescription>
            Crée l&apos;organisation et le site « lab », génère un code
            d&apos;enrôlement et le dépose dans le volume partagé surveillé par
            les players émulés. Les joueurs s&apos;enrôlent ensuite
            automatiquement (1 à 2 minutes).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Button onClick={install} disabled={busy}>
              {busy ? "Installation…" : "Installer les Raspberry Pi émulés"}
            </Button>
            {status && (
              <span className="text-xs text-muted-foreground">
                Volume enrôlement : {status.enroll_dir} —{" "}
                {status.enroll_dir_writable ? "accessible" : "non accessible"}
              </span>
            )}
          </div>

          {result && (
            <div className="rounded-lg border bg-muted/40 p-4 text-sm space-y-1">
              <p>
                <strong>Codes d&apos;enrôlement :</strong>{" "}
                {Object.entries(result.codes).map(([serial, code]) => (
                  <code
                    key={serial}
                    className="mr-3 rounded bg-muted px-1.5 py-0.5 font-mono"
                  >
                    {serial}: {code}
                  </code>
                ))}
              </p>
              <p className="text-muted-foreground">
                Site : {result.site} (org {result.org}) — expire le{" "}
                {new Date(result.expires_at).toLocaleString("fr-FR")} — déposé
                dans {result.code_files.join(", ")}
              </p>
            </div>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {status && (
        <Card>
          <CardHeader>
            <CardTitle>Players émulés</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {status.players.map((p) => (
                <div
                  key={p.serial}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3"
                >
                  <div>
                    <p className="font-medium font-mono text-sm">{p.serial}</p>
                    <p className="text-xs text-muted-foreground">
                      {p.enrolled
                        ? `${p.device_name} — ${
                            STATUS_LABEL[p.device_status ?? ""] ??
                            p.device_status ??
                            "?"
                          }`
                        : p.code_file_present
                          ? "Code déposé — enrôlement en cours…"
                          : "Non installé — cliquez sur Installer"}
                    </p>
                  </div>
                  <span
                    className={
                      "rounded-full px-2.5 py-0.5 text-xs font-medium " +
                      (p.device_status === "online"
                        ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                        : p.enrolled
                          ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                          : "bg-muted text-muted-foreground")
                    }
                  >
                    {p.enrolled ? (p.device_status ?? "?") : "absent"}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-muted-foreground">
              Les players enrôlés apparaissent aussi dans{" "}
              <strong>Appareils</strong> (à approuver après le premier
              enrôlement) et dans pi-admin.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
