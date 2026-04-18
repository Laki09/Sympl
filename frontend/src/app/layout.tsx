import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sympl",
  description: "Frontend for the Sympl AI workflow assistant.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
