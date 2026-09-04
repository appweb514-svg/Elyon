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
  computed_status?: string | null;
  site_id: string | null;
  screen_id: string | null;
  last_seen_at: string | null;
  player_state?: string | null;
  is_preview?: boolean;
  created_at: string;
};

type Site = { id: string; name: string };
type EnrollToken = { id: string; site_id: string; code: string; expires_at: string };
type SiteName = Record<string, string>;

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente d'approbation",
  approved: "Prêt (jamais connecté)",
  online: "En ligne",
  offline: "Hors ligne",
  syncing: "Mise à jour",
  maintenance: "Maintenance",
  disabled: "Désactivé",
  blocked: "Bloqué",
};

const STATE_LABEL: Record<string, string> = {
  playing: "diffuse",
  idle: "en attente",
  blank: "écran éteint",
};

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "online") return "success";
  if (status === "pending" || status === "syncing") return "warning";
  if (status === "blocked" || status === "disabled") return "destructive";
  return "secondary";
}

function displayStatus(d: Device): string {
  return d.computed_status ?? d.status;
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
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  useEffect(() => {
    reload();
    const timer = setInterval(() => {
      void reload();
    }, 10000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createToken() {
    try {
      const token = await api.post<EnrollToken>(
        `/api/enroll/tokens?site_id=${tokenSite}&ttl_seconds=3600`
      );
      setNewCode(token.code);
      setTokens((prev) => [...prev, token]);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function act(
    device: Device,
    action: "approve" | "block" | "disable" | "enable" | "maintenance" | "unblock"
  ) {
    try {
      const path =
        action === "maintenance"
          ? `/api/devices/${device.id}/maintenance`
          : `/api/devices/${device.id}/${action}`;
      await api.post(path);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function rotate(device: Device) {
    if (!window.confirm(`Régénérer le token de « ${device.name} » ? Il devra être réinstallé sur place.`)) {
      return;
    }
    try {
      await api.post(`/api/devices/${device.id}/rotate-token`);
      window.alert("Token régénéré : l'appareil devra être réinstallé.");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  const pending = devices.filter((d) => d.status === "pending");
  const active = devices.filter((d) => d.status !== "pending");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Appareils</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Vos écrans Raspberry Pi. Cliquez sur un appareil pour voir ce qu&apos;il affiche
            et gérer son contenu.
          </p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>+ Ajouter un appareil</Button>
      </div>
      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

      {pending.length > 0 && (
        <Card className="border-amber-300 bg-amber-50/50">
          <CardHeader>
            <CardTitle>Appareils en attente de votre accord</CardTitle>
            <CardDescription>
              Ces appareils viennent de se connecter pour la première fois. Approuvez-les pour
              pouvoir leur envoyer du contenu — ou rejetez-les s&apos;il s&apos;agit d&apos;un matériel inconnu.
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
                    <TableCell className="font-mono text-xs">{device.serial}</TableCell>
                    <TableCell>{formatDate(device.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-wrap justify-end gap-2">
                        <Button size="sm" onClick={() => act(device, "approve")}>
                          Approuver
                        </Button>
                        <Button size="sm" variant="destructive" onClick={() => act(device, "block")}>
                          Rejeter
                        </Button>
                      </div>
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
          <CardTitle>Tous les appareils ({active.length})</CardTitle>
          <CardDescription>
            « En ligne » = l&apos;écran fonctionne et diffuse. « Hors ligne » = le serveur n&apos;a
            plus de nouvelles (vérifiez l&apos;alimentation/le réseau). Cliquez sur un nom pour
            voir son aperçu en direct.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Appareil</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>En ce moment</TableHead>
                <TableHead>Dernier contact</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {active.map((device) => {
                const shown = displayStatus(device);
                return (
                  <TableRow key={device.id}>
                    <TableCell>
                      <Link href={`/devices/${device.id}`} className="font-medium hover:underline">
                        {device.name}
                      </Link>
                      {device.is_preview ? (
                        <Badge variant="warning" className="ml-2">aperçu</Badge>
                      ) : null}
                      <div className="text-xs text-muted-foreground">
                        {siteNames[device.site_id ?? ""] ?? "sans site"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(shown)}>{STATUS_LABEL[shown] ?? shown}</Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      {device.player_state === "playing" ? (
                        <span className="text-emerald-700">▶ {STATE_LABEL.playing}</span>
                      ) : device.player_state === "blank" ? (
                        <span className="text-muted-foreground">⬛ écran éteint</span>
                      ) : (
                        <span className="text-muted-foreground">… en attente de contenu</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {formatDate(device.last_seen_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-wrap justify-end gap-1">
                      {device.status === "blocked" ? (
                        <Button
                          size="sm"
                          onClick={() => act(device, "unblock")}
                          title="Autoriser à nouveau cet appareil (réenrôlement requis sur place)"
                        >
                          Débloquer
                        </Button>
                      ) : null}
                      {device.status === "disabled" || device.status === "maintenance" ? (
                        <Button size="sm" variant="outline" onClick={() => act(device, "enable")}>
                          Réactiver
                        </Button>
                      ) : null}
                      {device.status === "pending" ? (
                        <Button size="sm" onClick={() => act(device, "approve")}>
                          Approuver
                        </Button>
                      ) : null}
                      {device.status === "approved" && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={async () => {
                              try {
                                await api.post(`/api/devices/${device.id}/commands`, { type: "resync" });
                              } catch (err) {
                                setError(String((err as Error).message ?? err));
                              }
                            }}
                            title="Demander à l'écran de re-télécharger son contenu"
                          >
                            Mettre à jour
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => act(device, "disable")}
                            title="Suspendre la diffusion (l'appareil ne peut plus se connecter)"
                          >
                            Désactiver
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => rotate(device)} title="Invalider l'accès (matériel perdu)">
                            Sécuriser
                          </Button>
                          <Button size="sm" variant="destructive" onClick={() => act(device, "block")}>
                            Bloquer
                          </Button>
                        </>
                      )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {active.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Aucun appareil encore. Cliquez sur « + Ajouter un appareil » pour commencer.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {tokens.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Codes d&apos;installation générés</CardTitle>
            <CardDescription>
              À saisir sur l&apos;écran lors de son premier démarrage (valables 1 h).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              {tokens.map((token) => (
                <li key={token.id}>
                  <code className="rounded bg-muted px-2 py-0.5 font-mono text-lg tracking-widest">{token.code}</code>{" "}
                  <span className="text-muted-foreground">({siteNames[token.site_id] ?? "?"})</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ajouter un nouvel écran</DialogTitle>
            <DialogDescription>
              1. Choisissez le lieu (site) de l&apos;écran. 2. Un code à 6 caractères est
              généré. 3. Saisissez-le sur le Raspberry lors de son premier démarrage —
              il apparaîtra ici pour approbation.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="token-site">Lieu (site)</Label>
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
              Générer le code
            </Button>
          </DialogFooter>
          {newCode && (
            <div className="rounded-md bg-muted p-4 text-center">
              <p className="text-xs text-muted-foreground">Code à saisir sur l&apos;écran</p>
              <p className="font-mono text-3xl font-bold tracking-widest">{newCode}</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
