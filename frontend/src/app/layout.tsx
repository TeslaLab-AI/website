/**
 * Purpose:
 * Defines the root HTML document for the TeslaLab frontend.
 *
 * Responsibilities:
 * - Loads shared fonts and global styles.
 * - Sets product metadata used by browsers and search engines.
 */
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TeslaLab AI",
  description:
    "AI engineering workforce for B2B software. Connect a repository so TeslaLab can find, investigate, and safely fix routine engineering problems.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
