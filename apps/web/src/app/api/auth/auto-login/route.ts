import { NextRequest, NextResponse } from "next/server";

import { publicOrigin } from "@/lib/public-origin";

/**
 * Auto-login : pose une session API sans passer par la page de connexion.
 *
 * Utilisé quand la page de login est désactivée (ELYON_DISABLE_LOGIN) :
 * le middleware redirige ici, et ce handler ouvre une session avec les
 * identifiants fournis côté serveur (ELYON_AUTO_LOGIN_EMAIL / PASSWORD).
 * Sans identifiants configurés, on retombe sur la page de login classique.
 */

const API_ORIGIN = process.env.ELYON_API_URL ?? "http://127.0.0.1:8000";

function safeNext(request: NextRequest): string {
  const next = request.nextUrl.searchParams.get("next") ?? "/";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function originOf(request: NextRequest): string {
  return publicOrigin({
    requestOrigin: request.nextUrl.origin,
    envUrl: process.env.ELYON_PUBLIC_WEB_URL,
    forwardedHost: request.headers.get("x-forwarded-host"),
    forwardedProto: request.headers.get("x-forwarded-proto"),
    host: request.headers.get("host"),
  });
}

export async function GET(request: NextRequest) {
  const email = process.env.ELYON_AUTO_LOGIN_EMAIL;
  const password = process.env.ELYON_AUTO_LOGIN_PASSWORD;
  const origin = originOf(request);

  if (!email || !password) {
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("next", safeNext(request));
    return NextResponse.redirect(loginUrl);
  }

  const response = await fetch(`${API_ORIGIN}/api/auth/login`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie: request.headers.get("cookie") ?? "",
    },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("next", safeNext(request));
    return NextResponse.redirect(loginUrl);
  }

  const headers = new Headers();
  headers.set("location", new URL(safeNext(request), origin).toString());
  for (const setCookie of response.headers.getSetCookie?.() ?? []) {
    headers.append("set-cookie", setCookie);
  }
  return new NextResponse(null, { status: 307, headers });
}
