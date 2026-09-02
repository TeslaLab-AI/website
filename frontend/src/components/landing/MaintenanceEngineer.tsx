/**
 * Purpose:
 * Explains TeslaLab as a maintenance engineer for existing repositories.
 *
 * Responsibilities:
 * - Describe the product role without claiming production ownership.
 * - Show the repo → TeslaLab → pull request relationship visually.
 */

import { Frame } from "./Frame";

export function MaintenanceEngineer() {
  return (
    <section className="py-8" aria-labelledby="maintenance-heading">
      <div className="tl-rule" />
      <Frame className="grid items-center gap-12 py-16 lg:grid-cols-2">
        <div>
          <p className="tl-kicker">AI maintenance engineer</p>
          <h2
            id="maintenance-heading"
            className="mt-4 max-w-xl text-3xl font-semibold tracking-[-0.03em] sm:text-4xl"
          >
            A maintenance worker for a repository you already run.
          </h2>
          <p className="mt-5 max-w-lg leading-relaxed text-[var(--tl-muted)]">
            TeslaLab is built for existing B2B software. It finds routine work,
            investigates it, and proposes a change a human can review. It does
            not replace your team, and it does not own production.
          </p>
        </div>
        <div
          className="relative grid grid-cols-3 items-center gap-2 sm:gap-4"
          aria-hidden="true"
        >
          <div className="tl-panel flex aspect-square flex-col items-center justify-center p-4 text-center">
            <svg viewBox="0 0 48 48" className="h-12 w-12 text-[var(--tl-fg)]">
              <path
                fill="currentColor"
                d="M24 4C12.95 4 4 13.05 4 24.15c0 8.9 5.76 16.45 13.76 19.12.1.02.14-.04.14-.1v-3.36c-5.6 1.22-6.78-2.7-6.78-2.7-.9-2.33-2.23-2.95-2.23-2.95-1.83-1.25.14-1.22.14-1.22 2.02.14 3.08 2.08 3.08 2.08 1.8 3.08 4.71 2.19 5.86 1.67.18-1.3.7-2.19 1.28-2.7-4.47-.51-9.17-2.24-9.17-9.97 0-2.2.78-4 2.07-5.41-.21-.51-.9-2.56.2-5.33 0 0 1.69-.54 5.53 2.07A19.1 19.1 0 0124 13.8c1.71 0 3.43.23 5.04.68 3.84-2.61 5.52-2.07 5.52-2.07 1.1 2.77.41 4.82.2 5.33 1.3 1.41 2.07 3.21 2.07 5.41 0 7.75-4.71 9.45-9.2 9.95.72.62 1.36 1.85 1.36 3.73v5.52c0 .06.04.13.14.1C38.24 40.6 44 33.05 44 24.15 44 13.05 35.05 4 24 4z"
              />
            </svg>
            <p className="mt-3 text-xs font-medium">Your repo</p>
          </div>
          <div className="flex flex-col items-center gap-2">
            <span className="h-px w-full bg-[var(--tl-signal)]" />
            <span className="font-mono text-[0.6rem] uppercase tracking-[0.18em] text-[var(--tl-signal)]">
              maintain
            </span>
            <span className="h-px w-full bg-[var(--tl-signal)]" />
          </div>
          <div className="tl-panel flex aspect-square flex-col items-center justify-center border-[var(--tl-signal)] p-4 text-center">
            <span className="flex h-12 w-12 flex-col justify-between py-1">
              <span className="h-1 w-full bg-[var(--tl-signal)]" />
              <span className="h-1 w-[70%] bg-[var(--tl-fg)]" />
              <span className="h-1 w-[40%] bg-[var(--tl-fg)] opacity-50" />
            </span>
            <p className="mt-3 text-xs font-medium">TeslaLab</p>
          </div>
          <div className="col-span-3 mt-2 tl-panel flex items-center justify-between px-4 py-3">
            <p className="text-sm">Output</p>
            <p className="font-mono text-xs text-[var(--tl-signal)]">PULL REQUEST → HUMAN REVIEW</p>
          </div>
        </div>
      </Frame>
    </section>
  );
}
