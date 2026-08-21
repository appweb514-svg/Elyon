"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, formatDate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Dashboard = {
  devices_total: number;
  devices_online: number;
  devices_pending: number;
  media_count: number;
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
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }

  const cards = [
    {
      label: "Appareils",
      value: data.devices_total,
      href: "/devices",
      hint: `${data.devices_pending} en attente`,
    },
    {
      label: "En ligne",
      value: data.devices_online,
      href: "/devices",
      hint: `${data.devices_total - data.devices_online} hors ligne`,
    },
    {
      label: "Médias",
      value: data.media_count,
      href: "/media",
      hint: "bibliothèque",
    },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Tableau de bord</h1>
      <div className="grid gap-4 sm:grid-cols-3">
        {cards.map((card) => (
          <Link key={card.label} href={card.href}>
            <Card className="transition-shadow hover:shadow-md">
              <CardHeader>
                <CardDescription>{card.label}</CardDescription>
                <CardTitle className="text-3xl">{card.value}</CardTitle>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">{card.hint}</CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Derniers événements</CardTitle>
          <CardDescription>Activité récente des appareils et du serveur</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Horodatage</TableHead>
                <TableHead>Niveau</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Message</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.recent_events.map((event) => (
                <TableRow key={event.id}>
                  <TableCell className="whitespace-nowrap">{formatDate(event.created_at)}</TableCell>
                  <TableCell>
                    <Badge variant={levelVariant(event.level)}>{event.level}</Badge>
                  </TableCell>
                  <TableCell>{event.type}</TableCell>
                  <TableCell>{event.message}</TableCell>
                </TableRow>
              ))}
              {data.recent_events.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    Aucun événement pour le moment.
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
