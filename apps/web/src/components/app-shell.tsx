"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  CalendarClock,
  Clapperboard,
  FileVideo,
  LayoutDashboard,
  LayoutGrid,
  LogOut,
  MapPin,
  MonitorSmartphone,
  ScrollText,
  Users,
} from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { hasPermission, type Role } from "@/lib/permissions";

const NAV = [
  { href: "/", label: "Tableau de bord", icon: LayoutDashboard, perm: null },
  { href: "/devices", label: "Appareils", icon: MonitorSmartphone, perm: "device.view" as const },
  { href: "/media", label: "Médias", icon: FileVideo, perm: "media.view" as const },
  { href: "/playlists", label: "Playlists", icon: Clapperboard, perm: "playlist.view" as const },
  { href: "/schedules", label: "Plannings", icon: CalendarClock, perm: "schedule.view" as const },
  { href: "/sites", label: "Sites & écrans", icon: MapPin, perm: "screen.view" as const },
  { href: "/users", label: "Utilisateurs", icon: Users, perm: "user.view" as const },
  { href: "/audit", label: "Audit", icon: ScrollText, perm: "audit.view" as const },
  { href: "/layouts", label: "Dispositions", icon: LayoutGrid, perm: "screen.view" as const },
];

type Me = {
  id: string;
  email: string;
  full_name: string;
  role: string;
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => undefined);
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  const role = (me?.role ?? "viewer") as Role;

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <span className="text-lg font-bold">Elyon</span>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {NAV.filter((item) => item.perm === null || hasPermission(role, item.perm)).map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t p-4">
          {me && (
            <div className="mb-2 text-sm">
              <div className="font-medium">{me.full_name}</div>
              <div className="text-xs text-muted-foreground">
                {me.email} · {me.role}
              </div>
            </div>
          )}
          <Button variant="outline" size="sm" className="w-full" onClick={logout}>
            <LogOut /> Déconnexion
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-6xl p-6">{children}</div>
      </main>
    </div>
  );
}
