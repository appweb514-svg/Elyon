import { NextRequest, NextResponse } from "next/server";

const API_ORIGIN = process.env.ELYON_API_URL ?? "http://127.0.0.1:8000";

/** Déconnexion : appelle l'API (expire la session) puis vide les cookies. */
export async function POST(request: NextRequest) {
  try {
    await fetch(`${API_ORIGIN}/api/auth/logout`, {
      method: "POST",
      headers: { cookie: request.headers.get("cookie") ?? "" },
    });
  } catch {
    // L'API est peut-être arrêtée : on déconnecte quand même côté navigateur.
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set("elyon_session", "", { httpOnly: true, path: "/", maxAge: 0 });
  response.cookies.set("elyon_csrf", "", { httpOnly: false, path: "/", maxAge: 0 });
  return response;
}
