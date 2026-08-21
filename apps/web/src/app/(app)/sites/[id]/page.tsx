"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

type Screen = {
  id: string;
  site_id: string;
  name: string;
  width: number;
  height: number;
  orientation: string;
  device_id: string | null;
};

type Device = { id: string; name: string; status: string };
type Site = { id: string; name: string; timezone: string };

export default function SiteDetailPage() {
  const params = useParams<{ id: string }>();
  const siteId = params.id;
  const [site, setSite] = useState<Site | null>(null);
  const [screens, setScreens] = useState<Screen[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [width, setWidth] = useState("1920");
  const [height, setHeight] = useState("1080");
  const [orientation, setOrientation] = useState("landscape");
  const [deviceId, setDeviceId] = useState("");

  const reload = useCallback(async () => {
    try {
      const [siteData, screenList, deviceList] = await Promise.all([
        api.get<Site>(`/api/sites/${siteId}`),
        api.get<Screen[]>(`/api/sites/${siteId}/screens`),
        api.get<Device[]>("/api/devices"),
      ]);
      setSite(siteData);
      setScreens(screenList);
      setDevices(deviceList);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [siteId]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function createScreen() {
    if (!name.trim()) return;
    try {
      await api.post(`/api/sites/${siteId}/screens`, {
        name,
        width: Number.parseInt(width, 10) || 1920,
        height: Number.parseInt(height, 10) || 1080,
        orientation,
        device_id: deviceId || null,
      });
      setName("");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function removeScreen(screen: Screen) {
    if (!window.confirm(`Supprimer l'écran « ${screen.name} » ?`)) return;
    try {
      await api.del(`/api/screens/${screen.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  const deviceNames = Object.fromEntries(devices.map((d) => [d.id, d.name]));

  if (error && !site) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (!site) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/sites" className="text-sm text-muted-foreground hover:underline">
          ← Sites
        </Link>
        <h1 className="text-2xl font-bold">{site.name}</h1>
        <p className="text-sm text-muted-foreground">{site.timezone}</p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Nouvel écran</CardTitle>
          <CardDescription>
            Un écran peut être associé à un appareil enrôlé (optionnel).
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-6 md:items-end">
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="scr-name">Nom</Label>
            <Input
              id="scr-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Écran hall A"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="scr-w">Largeur</Label>
            <Input
              id="scr-w"
              type="number"
              value={width}
              onChange={(e) => setWidth(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="scr-h">Hauteur</Label>
            <Input
              id="scr-h"
              type="number"
              value={height}
              onChange={(e) => setHeight(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="scr-orient">Orientation</Label>
            <select
              id="scr-orient"
              value={orientation}
              onChange={(e) => setOrientation(e.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm shadow-sm"
            >
              <option value="landscape">Paysage</option>
              <option value="portrait">Portrait</option>
            </select>
          </div>
          <Button onClick={createScreen} disabled={!name.trim()}>
            Créer
          </Button>
          <div className="space-y-2 md:col-span-3">
            <Label htmlFor="scr-device">Appareil associé</Label>
            <select
              id="scr-device"
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm shadow-sm"
            >
              <option value="">— Aucun —</option>
              {devices
                .filter((d) => d.status === "approved")
                .map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.name}
                  </option>
                ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Écrans du site</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Définition</TableHead>
                <TableHead>Orientation</TableHead>
                <TableHead>Appareil</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {screens.map((screen) => (
                <TableRow key={screen.id}>
                  <TableCell className="font-medium">{screen.name}</TableCell>
                  <TableCell>
                    {screen.width}×{screen.height}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{screen.orientation}</Badge>
                  </TableCell>
                  <TableCell>
                    {screen.device_id ? (deviceNames[screen.device_id] ?? screen.device_id) : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="destructive" onClick={() => removeScreen(screen)}>
                      Supprimer
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {screens.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Aucun écran sur ce site.
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
