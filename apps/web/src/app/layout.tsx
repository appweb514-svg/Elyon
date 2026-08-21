import "./globals.css";

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
      <body>{children}</body>
    </html>
  );
}