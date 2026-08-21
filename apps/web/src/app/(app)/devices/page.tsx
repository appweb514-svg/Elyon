"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

type Site = { id: string; name: string };
type EnrollToken = { id: string; site_id: string; code: string; expires_at: string };

type SiteName = Record<string, string>;

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "approved") return "success";
  if (status === "pending") return "warning";
  if (status === "blocked" || status === "rejected") return "destructive";
  return "secondary";
}

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [tokens, setTokens] = useState<EnrollToken[]>([]);
  const [siteNames, setSiteNames] = useState<SiteName>({});
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [tokenSite, setTokenSite] = useState("");
  const [newCode, setNewCode] = useState<string | null>(null);

  async function reload() {
    try {
      const [deviceList, siteList] = await Promise.all([
        api.get<Device[]>("/api/devices"),
        api.get<Site[]>("/api/sites"),
      ]);
      setDevices(deviceList);
      setSites(siteList);
      if (siteList.length > 0 && !tokenSite) {
        setTokenSite(siteList[0].id);
      }
      const names: SiteName = {};
      for (const site of siteList) {
        names[site.id] = site.name;
      }
      setSiteNames(names);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createToken() {
    try {
      const token = await api.post<EnrollToken>(
        `/api/enroll/tokens?site_id=${tokenSite}&ttl_seconds=3600`
      );
      setNewCode(token.code);
      setTokens((prev) => [...prev, token]);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function act(device: Device, action: "approve" | "block") {
    try {
      await api.post(`/api/devices/${device.id}/${action}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function rotate(device: Device) {
    if (!window.confirm(`Régénérer le token de « ${device.name} » ? Il devra se réenrôler.`)) {
      return;
    }
    try {
      await api.post(`/api/devices/${device.id}/rotate-token`);
      window.alert("Token régénéré : l'appareil devra être réenrôlé.");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  const pending = devices.filter((d) => d.status === "pending");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Appareils</h1>
        <Button onClick={() => setDialogOpen(true)}>Générer un jeton d&apos;enrôlement</Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      {pending.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Demandes d&apos;enrôlement en attente</CardTitle>
            <CardDescription>
              Approuvez ou rejetez les nouveaux players avant qu&apos;ils ne diffusent.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nom</TableHead>
                  <TableHead>Numéro de série</TableHead>
                  <TableHead>Demandé le</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pending.map((device) => (
                  <TableRow key={device.id}>
                    <TableCell className="font-medium">{device.name}</TableCell>
                    <TableCell>{device.serial}</TableCell>
                    <TableCell>{formatDate(device.created_at)}</TableCell>
                    <TableCell className="space-x-2 text-right">
                      <Button size="sm" onClick={() => act(device, "approve")}>
                        Approuver
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => act(device, "block")}>
                        Rejeter
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Jetons d&apos;enrôlement actifs</CardTitle>
          <CardDescription>À saisir sur le player lors du premier démarrage.</CardDescription>
        </CardHeader>
        <CardContent>
          {tokens.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Aucun jeton généré pendant cette session. Générer un jeton pour enrôler un player.
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {tokens.map((token) => (
                <li key={token.id}>
                  <code className="rounded bg-muted px-2 py-0.5 font-mono">{token.code}</code>{" "}
                  <span className="text-muted-foreground">
                    ({siteNames[token.site_id] ?? "?"} — expire le {formatDate(token.expires_at)})
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tous les appareils</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Dernier contact</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {devices.map((device) => (
                <TableRow key={device.id}>
                  <TableCell>
                    <Link href={`/devices/${device.id}`} className="font-medium hover:underline">
                      {device.name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{device.serial}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(device.status)}>{device.status}</Badge>
                  </TableCell>
                  <TableCell>{formatDate(device.last_seen_at)}</TableCell>
                  <TableCell className="space-x-2 text-right">
                    {device.status === "approved" && (
                      <Button size="sm" variant="outline" onClick={() => rotate(device)}>
                        Régénérer le token
                      </Button>
                    )}
                    {device.status === "approved" && (
                      <Button size="sm" variant="destructive" onClick={() => act(device, "block")}>
                        Bloquer
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {devices.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    Aucun appareil enrôlé.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nouveau jeton d&apos;enrôlement</DialogTitle>
            <DialogDescription>
              Le code affiché sera à saisir sur le player (valable 60 minutes).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="token-site">Site</Label>
            <Select id="token-site" value={tokenSite} onChange={(e) => setTokenSite(e.target.value)}>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Fermer
            </Button>
            <Button onClick={createToken} disabled={!tokenSite}>
              Générer
            </Button>
          </DialogFooter>
          {newCode && (
            <div className="rounded-md bg-muted p-4 text-center">
              <p className="text-xs text-muted-foreground">Code d&apos;enrôlement</p>
              <p className="font-mono text-2xl font-bold tracking-widest">{newCode}</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
