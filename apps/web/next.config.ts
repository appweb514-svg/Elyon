import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    ELYON_PUBLIC_WEB_URL: process.env.ELYON_PUBLIC_WEB_URL ?? "",
    ELYON_DISABLE_LOGIN: process.env.ELYON_DISABLE_LOGIN ?? "",
  },
  async headers() {
    return [
      {
        source: "/((?!_next/static|_next/image|favicon.ico).*)",
        headers: [{ key: "Cache-Control", value: "no-cache, must-revalidate" }],
      },
    ];
  },
};

export default nextConfig;
