import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy générique vers l'API Elyon.
 *
 * Le navigateur ne parle jamais directement à l'API : tout passe par ici.
 * Les cookies (session httpOnly + CSRF) sont transmis dans les deux sens,
 * ce qui fait de la session API la session du back-office.
 */

const API_ORIGIN = process.env.ELYON_API_URL ?? "http://127.0.0.1:8000";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
]);

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const url = new URL(request.nextUrl.search, `${API_ORIGIN}/api/${path.join("/")}`);
  const upstream = new Request(url, {
    method: request.method,
    headers: request.headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
    redirect: "manual",
  });

  const response = await fetch(upstream);
  const headers = new Headers();
  response.headers.forEach((value, name) => {
    if (!HOP_BY_HOP.has(name.toLowerCase()) && name.toLowerCase() !== "set-cookie") {
      headers.set(name, value);
    }
  });
  for (const setCookie of response.headers.getSetCookie?.() ?? []) {
    headers.append("set-cookie", setCookie);
  }

  return new NextResponse(response.body, {
    status: response.status,
    headers,
  });
}

type RouteContext = { params: Promise<{ elyon: string[] }> };

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).elyon);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).elyon);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).elyon);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).elyon);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).elyon);
}
