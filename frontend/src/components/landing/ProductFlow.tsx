/**
 * Purpose:
 * Shows the intended TeslaLab maintenance workflow.
 *
 * Responsibilities:
 * - Communicate detect-to-review as a visual operating sequence.
 */

import { productFlowSteps } from "./content";
import { Frame } from "./Frame";

export function ProductFlow() {
  return (
    <section className="pb-8" aria-labelledby="flow-heading">
      <Frame>
        <p className="tl-kicker">Product flow</p>
        <h2
          id="flow-heading"
          className="mt-3 text-3xl font-semibold tracking-[-0.03em]"
        >
          From detection to human review.
        </h2>
        <ol className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
          {productFlowSteps.map((step, index) => (
            <li key={step} className="tl-panel relative min-h-[10.5rem] p-4">
              <span
                className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--tl-signal)] font-mono text-xs text-[var(--tl-signal)]"
                aria-hidden="true"
              >
                {String(index + 1).padStart(2, "0")}
              </span>
              {index < productFlowSteps.length - 1 ? (
                <span
                  className="absolute top-8 right-[-0.55rem] hidden h-px w-3 bg-[var(--tl-signal)] lg:block"
                  aria-hidden="true"
                />
              ) : null}
              <p className="mt-8 text-sm font-semibold leading-snug">{step}</p>
            </li>
          ))}
        </ol>
      </Frame>
    </section>
  );
}
