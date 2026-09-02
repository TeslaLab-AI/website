/**
 * Purpose:
 * Communicates TeslaLab safety constraints around code changes.
 *
 * Responsibilities:
 * - State that AI may modify code but must not own production.
 * - Emphasize controlled execution, validation, and human review.
 */

import { Frame } from "./Frame";

const constraints = [
  "Controlled execution",
  "Isolated environment",
  "Validation before proposal",
  "PR-based changes",
  "Human review",
];

export function Safety() {
  return (
    <section className="py-6" aria-labelledby="safety-heading">
      <div className="tl-rule" />
      <Frame className="py-20">
        <p className="tl-kicker">Safety</p>
        <blockquote
          id="safety-heading"
          className="mt-6 max-w-3xl border-l-2 border-[var(--tl-signal)] pl-6 text-3xl font-semibold leading-tight tracking-[-0.03em] sm:text-5xl"
        >
          AI can touch code.
          <br />
          It should not own production.
        </blockquote>
        <ul className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {constraints.map((item) => (
            <li
              key={item}
              className="border border-[var(--tl-line)] px-4 py-5 text-sm"
            >
              {item}
            </li>
          ))}
        </ul>
      </Frame>
    </section>
  );
}
