/**
 * Purpose:
 * Renders the TeslaLab landing-page footer.
 *
 * Responsibilities:
 * - Provide a quiet close without fake social proof.
 */

import { Frame } from "./Frame";

export function Footer() {
  return (
    <footer className="relative z-[1] border-t border-[var(--tl-line)] py-8">
      <Frame className="flex flex-col gap-1 text-xs text-[var(--tl-muted)] sm:flex-row sm:items-center sm:justify-between">
        <p className="tracking-[0.16em]">TESLALAB AI</p>
        <p>AI engineering workforce for B2B software.</p>
      </Frame>
    </footer>
  );
}
