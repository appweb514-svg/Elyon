"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Activity,
  CalendarClock,
  Clapperboard,
  FileVideo,
  LayoutDashboard,
  LogOut,
  MapPin,
  Menu,
  MonitorSmartphone,
  ScrollText,
  Users,
  UsersRound,
  Layers,
  LayoutGrid,
  Cpu,
  X,
} from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { hasPermission, type Role } from "@/lib/permissions";
import { ThemeToggle } from "@/components/theme-toggle";

const NAV = [
  { href: "/", label: "Tableau de bord", icon: LayoutDashboard, perm: null },
  { href: "/wall", label: "Mur d'écrans", icon: LayoutGrid, perm: "device.view" as const },
  { href: "/devices", label: "Appareils", icon: MonitorSmartphone, perm: "device.view" as const },
  { href: "/groups", label: "Groupes", icon: Layers, perm: "device.view" as const },
  { href: "/media", label: "Médias", icon: FileVideo, perm: "media.view" as const },
  { href: "/playlists", label: "Playlists", icon: Clapperboard, perm: "playlist.view" as const },
  { href: "/schedules", label: "Plannings", icon: CalendarClock, perm: "schedule.view" as const },
  { href: "/sites", label: "Sites & écrans", icon: MapPin, perm: "screen.view" as const },
  { href: "/users", label: "Utilisateurs", icon: Users, perm: "user.view" as const },
  { href: "/teams", label: "Équipes", icon: UsersRound, perm: "user.view" as const },
  { href: "/audit", label: "Audit", icon: ScrollText, perm: "audit.view" as const },
  { href: "/lab", label: "Pi émulés", icon: Cpu, superadminOnly: true as const },
];

type Me = {
  id: string;
  email: string;
  full_name: string;
  role: string;
};

const ROLE_LABEL: Record<string, string> = {
  superadmin: "Super-admin",
  org_admin: "Admin IT",
  site_manager: "Responsable de site",
  operator: "Contributeur",
  viewer: "Lecteur",
};

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-1">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-indigo-600 shadow-lg shadow-primary/30">
        <Activity className="h-5 w-5 text-primary-foreground" />
      </span>
      <div className="hidden leading-tight min-[380px]:block">
        <p className="text-base font-bold tracking-tight">Elyon</p>
        <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Affichage dynamique
        </p>
      </div>
    </Link>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => undefined);
  }, []);

  const role = (me?.role ?? "viewer") as Role;

  return (
    <nav className="flex-1 space-y-1 p-2">
      {NAV.filter((item) => ("superadminOnly" in item && item.superadminOnly ? role === "superadmin" : item.perm === null || hasPermission(role, item.perm))).map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200",
              active
                ? "bg-primary text-primary-foreground shadow-md shadow-primary/25"
                : "text-muted-foreground hover:translate-x-0.5 hover:bg-accent hover:text-accent-foreground"
            )}
          >
            <item.icon
              className={cn(
                "h-4 w-4 transition-transform duration-200 group-hover:scale-110",
                active && "scale-105"
              )}
            />
            {item.label}
            {active && (
              <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r bg-primary-foreground/60" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex h-16 items-center border-b px-4">
          <Logo />
        </div>
        <NavLinks />
        <div className="border-t p-4">
          {me && (
            <div className="mb-3 flex items-center justify-between rounded-lg bg-muted/60 px-3 py-2">
              <button
                type="button"
                onClick={() => router.push("/profile")}
                className="min-w-0 flex-1 text-left transition-colors hover:text-primary"
                title="Modifier mon profil"
              >
                <div className="truncate text-sm font-medium">{me.full_name}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {ROLE_LABEL[me.role] ?? me.role}
                </div>
              </button>
              <ThemeToggle />
            </div>
          )}
          <Button variant="outline" size="sm" className="w-full" onClick={logout}>
            <LogOut /> Déconnexion
          </Button>
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/40 animate-fade-in"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="animate-enter absolute inset-y-0 left-0 flex w-72 flex-col bg-card shadow-2xl">
            <div className="flex h-16 items-center justify-between border-b px-4">
              <Logo />
              <Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)} aria-label="Fermer">
                <X />
              </Button>
            </div>
            <NavLinks onNavigate={() => setMobileOpen(false)} />
            <div className="border-t p-4">
              {me && (
                <div className="mb-3 truncate text-xs text-muted-foreground">
                  {me.email} · {ROLE_LABEL[me.role] ?? me.role}
                </div>
              )}
              <Button variant="outline" size="sm" className="w-full" onClick={logout}>
                <LogOut /> Déconnexion
              </Button>
            </div>
          </aside>
        </div>
      )}

      <main className="flex-1 overflow-x-hidden">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-background/80 px-4 backdrop-blur md:hidden">
          <Logo />
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <Button variant="ghost" size="icon" onClick={() => setMobileOpen(true)} aria-label="Menu">
              <Menu />
            </Button>
          </div>
        </header>
        <div key={pathname} className="animate-enter mx-auto max-w-7xl p-4 sm:p-6">
          {children}
        </div>
      </main>
    </div>
  );
}
