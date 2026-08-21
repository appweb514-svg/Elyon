import { NextRequest, NextResponse } from "next/server";

const API_ORIGIN = process.env.ELYON_API_URL ?? "http://127.0.0.1:8000";

/**
 * Login : proxifie vers l'API, qui pose elle-même le cookie de session
 * httpOnly (Set-Cookie retransmis tel quel au navigateur).
 */
export async function POST(request: NextRequest) {
  const body = await request.arrayBuffer();
  const response = await fetch(`${API_ORIGIN}/api/auth/login`, {
    method: "POST",
    headers: {
      "content-type": request.headers.get("content-type") ?? "application/json",
      cookie: request.headers.get("cookie") ?? "",
    },
    body,
  });

  const headers = new Headers();
  headers.set("content-type", "application/json");
  for (const setCookie of response.headers.getSetCookie?.() ?? []) {
    headers.append("set-cookie", setCookie);
  }

  return new NextResponse(response.body, { status: response.status, headers });
}
