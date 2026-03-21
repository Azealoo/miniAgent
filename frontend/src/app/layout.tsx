import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BioAPEX",
  description: "Transparent, file-first scientific workspace",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="overflow-hidden antialiased text-slate-900">
        {children}
      </body>
    </html>
  );
}
