/**
 * Purpose:
 * Describes the intended TeslaLab operating steps after GitHub is connected.
 *
 * Responsibilities:
 * - Walk through connect, detect, execute, validate, and human review.
 */

import { howItWorksSteps } from "./content";
import { Frame } from "./Frame";

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="scroll-mt-24 py-6"
      aria-labelledby="how-heading"
    >
      <div className="tl-rule" />
      <Frame className="grid gap-12 py-20 lg:grid-cols-12">
        <div className="lg:col-span-4">
          <p className="tl-kicker">How it works</p>
          <h2
            id="how-heading"
            className="mt-3 text-3xl font-semibold tracking-[-0.03em]"
          >
            Nine steps. One reviewable change.
          </h2>
          <p className="mt-5 max-w-sm text-sm leading-relaxed text-[var(--tl-muted)]">
            The intended operating model after you connect GitHub. Work is
            proposed as a pull request — not a production deploy.
          </p>
        </div>
        <ol className="relative lg:col-span-8">
          <span
            aria-hidden="true"
            className="absolute top-2 bottom-2 left-[0.85rem] w-px bg-[var(--tl-line)]"
          />
          {howItWorksSteps.map((step, index) => (
            <li key={step} className="relative flex gap-5 pb-6 last:pb-0">
              <span className="relative z-[1] flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--tl-line)] bg-[var(--tl-bg)] font-mono text-[0.65rem] text-[var(--tl-signal)]">
                {String(index + 1).padStart(2, "0")}
              </span>
              <p className="pt-1 text-[0.95rem] leading-relaxed">{step}</p>
            </li>
          ))}
        </ol>
      </Frame>
    </section>
  );
}
