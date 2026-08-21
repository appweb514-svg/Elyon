import "./globals.css";
import { Suspense } from "react";

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
      <body>
        <Suspense>{children}</Suspense>
      </body>
    </html>
  );
}
