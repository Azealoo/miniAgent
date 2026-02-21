import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "mini OpenClaw",
  description: "Lightweight, transparent AI Agent system",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased bg-[#fafafa] text-gray-900 overflow-hidden">
        {children}
      </body>
    </html>
  );
}
