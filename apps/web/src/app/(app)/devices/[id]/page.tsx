"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, formatDate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Device = {
  id: string;
  name: string;
  serial: string;
  status: string;
  site_id: string | null;
  screen_id: string | null;
  last_seen_at: string | null;
  created_at: string;
};

type Heartbeat = {
  state: string;
  current_media_id: string | null;
  storage_free_bytes: number | null;
  agent_version: string | null;
  created_at: string;
};

type Command = {
  id: string;
  type: string;
  payload: string | null;
  status: string;
  created_at: string;
};

const COMMAND_TYPES = ["reboot", "resync", "blank", "unblank", "capture"] as const;

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "approved") return "success";
  if (status === "pending") return "warning";
  if (status === "blocked" || status === "rejected") return "destructive";
  return "secondary";
}

export default function DeviceDetailPage() {
  const params = useParams<{ id: string }>();
  const deviceId = params.id;
  const [device, setDevice] = useState<Device | null>(null);
  const [heartbeat, setHeartbeat] = useState<Heartbeat | null>(null);
  const [commands, setCommands] = useState<Command[]>([]);
  const [manifestVersion, setManifestVersion] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [commandType, setCommandType] = useState<string>("resync");

  const reload = useCallback(async () => {
    try {
      setDevice(await api.get<Device>(`/api/devices/${deviceId}`));
      setHeartbeat(await api.get<Heartbeat>(`/api/devices/${deviceId}/heartbeat`));
      setCommands(await api.get<Command[]>(`/api/devices/${deviceId}/commands`));
      const manifest = await api.get<{ version: number }>(`/api/devices/${deviceId}/manifest`);
      setManifestVersion(manifest.version);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [deviceId]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function sendCommand() {
    try {
      await api.post(`/api/devices/${deviceId}/commands`, { type: commandType });
      setNotice(`Commande « ${commandType} » envoyée.`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function publish() {
    try {
      const manifest = await api.post<{ version: number }>(
        `/api/devices/${deviceId}/publish`
      );
      setNotice(`Publication effectuée (version ${manifest.version}).`);
      setManifestVersion(manifest.version);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  if (error && !device) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (!device) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{device.name}</h1>
          <p className="text-sm text-muted-foreground">
            Série {device.serial} ·{" "}
            <Badge variant={statusVariant(device.status)}>{device.status}</Badge>
          </p>
        </div>
        <Button onClick={publish}>Publier maintenant</Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {notice && <p className="text-sm text-emerald-600">{notice}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>État</CardTitle>
            <CardDescription>Dernier contact : {formatDate(device.last_seen_at)}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>
              État agent :{" "}
              <strong>{heartbeat ? heartbeat.state : "—"}</strong>
            </p>
            <p>
              Version agent : <strong>{heartbeat?.agent_version ?? "—"}</strong>
            </p>
            <p>
              Stockage libre : <strong>{heartbeat?.storage_free_bytes ?? "—"} octets</strong>
            </p>
            <p>
              Média en cours : <strong>{heartbeat?.current_media_id ?? "—"}</strong>
            </p>
            <p>
              Version du manifeste : <strong>{manifestVersion ?? "—"}</strong>
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Envoyer une commande</CardTitle>
            <CardDescription>
              La commande sera traitée au prochain cycle de l&apos;agent.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="command-type">Type</Label>
              <Select
                id="command-type"
                value={commandType}
                onChange={(e) => setCommandType(e.target.value)}
              >
                {COMMAND_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Select>
            </div>
            <Button onClick={sendCommand}>Envoyer</Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Historique des commandes</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Horodatage</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Payload</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {commands.map((command) => (
                <TableRow key={command.id}>
                  <TableCell className="whitespace-nowrap">{formatDate(command.created_at)}</TableCell>
                  <TableCell>{command.type}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        command.status === "acked"
                          ? "success"
                          : command.status === "error"
                            ? "destructive"
                            : "secondary"
                      }
                    >
                      {command.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-48 truncate">{command.payload ?? "—"}</TableCell>
                </TableRow>
              ))}
              {commands.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    Aucune commande envoyée.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
