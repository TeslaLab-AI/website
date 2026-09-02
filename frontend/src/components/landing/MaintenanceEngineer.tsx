/**
 * Purpose:
 * Explains TeslaLab as a maintenance engineer for existing repositories.
 *
 * Responsibilities:
 * - Describe the product role without claiming production ownership.
 */

import { Frame } from "./Frame";

export function MaintenanceEngineer() {
  return (
    <section className="py-20" aria-labelledby="maintenance-heading">
      <div className="tl-rule" />
      <Frame className="grid gap-10 py-20 lg:grid-cols-12">
        <p className="tl-kicker lg:col-span-4">AI maintenance engineer</p>
        <div className="lg:col-span-8">
          <h2
            id="maintenance-heading"
            className="max-w-2xl text-3xl font-semibold tracking-[-0.03em] sm:text-4xl"
          >
            An engineering maintenance worker for a repository you already run.
          </h2>
          <p className="mt-6 max-w-xl text-base leading-relaxed text-[var(--tl-muted)]">
            TeslaLab is built for existing B2B software. It finds routine work,
            investigates it, and proposes a change a human can review. It does
            not replace your engineering team, and it does not take ownership of
            production.
          </p>
        </div>
      </Frame>
    </section>
  );
}
