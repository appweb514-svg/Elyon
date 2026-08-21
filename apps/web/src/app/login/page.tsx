"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "bootstrap">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") {
        await api.post("/api/auth/login", { email, password });
      } else {
        // Première installation : superadmin (bootstrap) → session → organisation.
        await api.post("/api/auth/bootstrap", { email, password });
        await api.post("/api/auth/login", { email, password });
        const slug =
          orgName
            .toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 40) || "org";
        await api.post(`/api/organizations?name=${encodeURIComponent(orgName)}&slug=${encodeURIComponent(slug)}`);
      }
      const next = params.get("next");
      router.push(next && next.startsWith("/") ? next : "/");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        if (mode === "login" && err.status === 403 && err.detail.includes("initialisé")) {
          setError("Le serveur est déjà initialisé — connectez-vous.");
        } else if (err.status === 401 && mode === "login") {
          setError("Identifiants invalides");
        } else {
          setError(err.detail);
        }
      } else {
        setError("Impossible de contacter le serveur");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-2xl">Elyon</CardTitle>
          <CardDescription>
            {mode === "login"
              ? "Connectez-vous au back-office d'affichage dynamique."
              : "Première installation : créez votre organisation et le compte administrateur."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            {mode === "bootstrap" && (
              <div className="space-y-2">
                <Label htmlFor="org">Nom de l&apos;organisation</Label>
                <Input
                  id="org"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="Mairie de Trifouilly"
                  required
                  minLength={1}
                />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">Adresse e-mail</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@exemple.fr"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Mot de passe</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={mode === "bootstrap" ? 12 : 1}
              />
              {mode === "bootstrap" && (
                <p className="text-xs text-muted-foreground">
                  12 caractères minimum pour le compte administrateur.
                </p>
              )}
            </div>
            {error && (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy
                ? "…"
                : mode === "login"
                  ? "Se connecter"
                  : "Initialiser et se connecter"}
            </Button>
          </form>
          <button
            type="button"
            className="mt-4 w-full text-center text-sm text-muted-foreground underline-offset-4 hover:underline"
            onClick={() => {
              setMode(mode === "login" ? "bootstrap" : "login");
              setError(null);
            }}
          >
            {mode === "login"
              ? "Première installation ?"
              : "J'ai déjà un compte"}
          </button>
        </CardContent>
      </Card>
    </div>
  );
}
