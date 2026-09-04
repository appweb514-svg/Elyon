"use client";

import { useCallback, useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

type Device = {
  id: string;
  name: string;
  serial: string;
  status: string;
  is_preview?: boolean;
};

type Group = {
  id: string;
  name: string;
  device_ids: string[];
};

const GROUP_COMMANDS = ["reboot", "resync", "blank", "unblank"] as const;

export default function DeviceGroupsPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [cmdType, setCmdType] = useState<string>("resync");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [g, d] = await Promise.all([
        api.get<Group[]>("/api/device-groups"),
        api.get<Device[]>("/api/devices"),
      ]);
      setGroups(g);
      setDevices(d);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function createGroup() {
    if (!name.trim() || selected.length === 0) {
      setError("Nom et au moins un appareil requis.");
      return;
    }
    try {
      await api.post(`/api/device-groups?name=${encodeURIComponent(name.trim())}`, selected);
      setName("");
      setSelected([]);
      setNotice("Groupe créé.");
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function deleteGroup(group: Group) {
    if (!window.confirm(`Supprimer le groupe « ${group.name} » ?`)) return;
    try {
      await api.del(`/api/device-groups/${group.id}`);
      await reload();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function sendGroupCommand(group: Group) {
    try {
      const res = await api.post<{ command: string; devices: number }>(
        `/api/device-groups/${group.id}/commands`,
        { type: cmdType }
      );
      setNotice(`Commande « ${res.command} » envoyée à ${res.devices} appareil(s).`);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  function toggleDevice(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Groupes d&apos;appareils</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Regroupez des écrans pour leur envoyer une même commande (redémarrage,
          mise à jour, extinction) d&apos;un seul geste.
        </p>
      </div>
      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {notice && <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Nouveau groupe</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="group-name">Nom</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="RDC — Vitrines"
            />
          </div>
          <div>
            <Label className="mb-2 block">Appareils du groupe</Label>
            <div className="grid max-h-52 gap-1 overflow-auto rounded-md border p-2 sm:grid-cols-2">
              {devices
                .filter((d) => d.status !== "blocked" && d.status !== "disabled")
                .map((d) => (
                  <label
                    key={d.id}
                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-accent"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(d.id)}
                      onChange={() => toggleDevice(d.id)}
                    />
                    <span className="truncate">{d.name}</span>
                    {d.is_preview && <Badge variant="warning">aperçu</Badge>}
                  </label>
                ))}
            </div>
          </div>
          <Button onClick={createGroup} disabled={!name.trim() || selected.length === 0}>
            Créer le groupe
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tous les groupes ({groups.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {groups.map((group) => (
            <div key={group.id} className="flex flex-wrap items-center gap-3 rounded-md border p-3">
              <Layers className="h-4 w-4 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{group.name}</p>
                <p className="text-xs text-muted-foreground">
                  {group.device_ids.length} appareil(s)
                </p>
              </div>
              <Select
                value={cmdType}
                onChange={(e) => setCmdType(e.target.value)}
                className="w-full sm:w-44"
                aria-label="Commande du groupe"
              >
                {GROUP_COMMANDS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
              <Button
                size="sm"
                variant="outline"
                onClick={() => sendGroupCommand(group)}
                disabled={group.device_ids.length === 0}
              >
                Envoyer
              </Button>
              <Button size="sm" variant="destructive" onClick={() => deleteGroup(group)}>
                Supprimer
              </Button>
            </div>
          ))}
          {groups.length === 0 && (
            <p className="text-sm text-muted-foreground">Aucun groupe — créez le premier ci-dessus.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
