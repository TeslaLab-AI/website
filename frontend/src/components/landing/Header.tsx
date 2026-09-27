/**
 * Purpose:
 * Renders the TeslaLab landing-page header.
 *
 * Responsibilities:
 * - Identifies the product.
 * - Provides primary navigation to login, registration, and on-page sections.
 */

import Link from "next/link";
import { Frame } from "./Frame";

export function Header() {
  return (
    <header className="sticky top-0 z-20 border-b border-[var(--tl-line)] bg-[color-mix(in_srgb,var(--tl-bg)_88%,transparent)] backdrop-blur-md">
      <Frame className="flex items-center justify-between gap-4 py-4">
        <Link href="/" className="flex items-center gap-3 text-[var(--tl-fg)]">
          <span className="flex h-7 w-7 flex-col justify-between py-0.5" aria-hidden="true">
            <span className="h-[2px] w-full bg-[var(--tl-signal)]" />
            <span className="h-[2px] w-[70%] bg-[var(--tl-fg)]" />
            <span className="h-[2px] w-[40%] bg-[var(--tl-fg)] opacity-50" />
          </span>
          <span className="text-sm font-semibold tracking-[0.2em]">TESLALAB</span>
        </Link>
        <nav aria-label="Primary" className="flex items-center gap-1 sm:gap-3 text-sm">
          <Link
            href="#how-it-works"
            className="hidden px-2 py-1 text-[var(--tl-muted)] hover:text-[var(--tl-fg)] sm:inline"
          >
            How it works
          </Link>
          <Link
            href="/login"
            className="px-2 py-1 text-[var(--tl-muted)] hover:text-[var(--tl-fg)]"
          >
            Log in
          </Link>
          <Link href="/register" className="tl-btn-primary">
            Get started
          </Link>
        </nav>
      </Frame>
    </header>
  );
}
