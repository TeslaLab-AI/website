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
      className="scroll-mt-24 py-8"
      aria-labelledby="how-heading"
    >
      <div className="tl-rule" />
      <Frame className="py-16">
        <div className="max-w-xl">
          <p className="tl-kicker">How it works</p>
          <h2
            id="how-heading"
            className="mt-3 text-3xl font-semibold tracking-[-0.03em]"
          >
            Nine steps. One reviewable change.
          </h2>
        </div>
        <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {howItWorksSteps.map((step, index) => (
            <li key={step} className="tl-panel relative overflow-hidden p-5 min-h-[9.5rem]">
              <span className="font-mono text-4xl font-semibold leading-none text-[var(--tl-signal)] opacity-80">
                {String(index + 1).padStart(2, "0")}
              </span>
              <p className="mt-6 text-sm font-medium leading-relaxed">{step}</p>
            </li>
          ))}
        </ol>
      </Frame>
    </section>
  );
}
