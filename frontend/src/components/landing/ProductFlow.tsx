/**
 * Purpose:
 * Shows the intended TeslaLab maintenance workflow.
 *
 * Responsibilities:
 * - Communicate detect-to-review as the product operating sequence.
 */

import { productFlowSteps } from "./content";
import { Frame } from "./Frame";

export function ProductFlow() {
  return (
    <section className="pb-20" aria-labelledby="flow-heading">
      <Frame>
        <div className="flex items-end justify-between gap-6">
          <div>
            <p className="tl-kicker">Product flow</p>
            <h2
              id="flow-heading"
              className="mt-3 text-3xl font-semibold tracking-[-0.03em]"
            >
              From detection to human review.
            </h2>
          </div>
        </div>
        <ol className="mt-10 grid gap-px bg-[var(--tl-line)] sm:grid-cols-2 lg:grid-cols-7">
          {productFlowSteps.map((step, index) => (
            <li
              key={step}
              className="min-h-[9.5rem] bg-[var(--tl-bg)] p-4"
            >
              <span className="font-mono text-[0.7rem] text-[var(--tl-signal)]">
                {String(index + 1).padStart(2, "0")}
              </span>
              <p className="mt-8 text-sm font-medium leading-snug">{step}</p>
            </li>
          ))}
        </ol>
      </Frame>
    </section>
  );
}
