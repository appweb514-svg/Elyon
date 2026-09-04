import "./globals.css";
import { Suspense } from "react";

import { GlowBackground } from "@/components/glow-background";

export const metadata = {
  title: "Elyon",
  description: "Affichage dynamique centralisé",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body className="min-h-screen">
        <GlowBackground />
        <Suspense>{children}</Suspense>
      </body>
    </html>
  );
}
