import { NextRequest, NextResponse } from "next/server";

import { publicOrigin } from "@/lib/public-origin";

const PUBLIC_PATHS = ["/login"];

function originOf(request: NextRequest): string {
  return publicOrigin({
    requestOrigin: request.nextUrl.origin,
    envUrl: process.env.ELYON_PUBLIC_WEB_URL,
    forwardedHost: request.headers.get("x-forwarded-host"),
    forwardedProto: request.headers.get("x-forwarded-proto"),
    host: request.headers.get("host"),
  });
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has("elyon_session");
  const origin = originOf(request);

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    if (hasSession && pathname === "/login") {
      return NextResponse.redirect(new URL("/", origin));
    }
    return NextResponse.next();
  }

  if (!hasSession) {
    const autoLogin = new URL("/api/auth/auto-login", origin);
    autoLogin.searchParams.set("next", pathname);
    return NextResponse.redirect(autoLogin);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
