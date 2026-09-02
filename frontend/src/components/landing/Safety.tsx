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
    <section className="py-8" aria-labelledby="safety-heading">
      <div className="tl-rule" />
      <Frame className="grid items-center gap-12 py-16 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <p className="tl-kicker">Safety</p>
          <blockquote
            id="safety-heading"
            className="mt-5 text-3xl font-semibold leading-[1.1] tracking-[-0.03em] sm:text-5xl"
          >
            AI can touch code.
            <br />
            <span className="text-[var(--tl-signal)]">It should not own production.</span>
          </blockquote>
          <ul className="mt-10 grid gap-3 sm:grid-cols-2">
            {constraints.map((item) => (
              <li
                key={item}
                className="flex items-center gap-3 border border-[var(--tl-line)] px-4 py-4 text-sm"
              >
                <span className="h-2 w-2 shrink-0 bg-[var(--tl-signal)]" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div className="tl-panel relative flex min-h-[22rem] items-center justify-center overflow-hidden p-8">
          <svg viewBox="0 0 280 280" className="h-full w-full max-w-xs" aria-hidden="true">
            <rect x="70" y="40" width="140" height="90" fill="none" stroke="rgba(243,238,228,0.2)" strokeWidth="2" />
            <text x="140" y="90" textAnchor="middle" fill="#9b9589" fontSize="12" fontFamily="monospace">
              PRODUCTION
            </text>
            <path d="M140 130 v28" stroke="#ff5e3a" strokeWidth="2" />
            <rect x="88" y="158" width="104" height="72" fill="none" stroke="#ff5e3a" strokeWidth="2" />
            <text x="140" y="188" textAnchor="middle" fill="#f3eee4" fontSize="12" fontFamily="monospace">
              PULL REQUEST
            </text>
            <text x="140" y="208" textAnchor="middle" fill="#ff5e3a" fontSize="11" fontFamily="monospace">
              HUMAN GATE
            </text>
            <circle cx="140" cy="158" r="6" fill="#08090b" stroke="#ff5e3a" strokeWidth="2" />
          </svg>
        </div>
      </Frame>
    </section>
  );
}
