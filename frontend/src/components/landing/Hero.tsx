/**
 * Purpose:
 * Renders the TeslaLab landing-page hero.
 *
 * Responsibilities:
 * - States the product positioning and core message.
 * - Provides the primary and secondary calls to action.
 */

import Link from "next/link";
import { productFlowSteps } from "./content";
import { Frame } from "./Frame";

export function Hero() {
  return (
    <section className="relative py-20 sm:py-28" aria-labelledby="hero-heading">
      <Frame className="grid items-end gap-12 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.85fr)]">
        <div>
          <p className="tl-kicker">TeslaLab AI</p>
          <h1
            id="hero-heading"
            className="mt-5 max-w-xl text-[2.6rem] font-semibold leading-[1.05] tracking-[-0.04em] sm:text-6xl"
          >
            AI engineering
            <br />
            workforce for
            <br />
            <span className="text-[var(--tl-signal)]">B2B software.</span>
          </h1>
          <p className="mt-7 max-w-md text-lg leading-relaxed text-[var(--tl-muted)]">
            Connect your repository. TeslaLab continuously finds, investigates,
            and safely fixes routine engineering problems.
          </p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row">
            <Link href="/register" className="tl-btn-primary">
              Connect GitHub
            </Link>
            <Link href="#how-it-works" className="tl-btn-ghost">
              See how it works
            </Link>
          </div>
        </div>

        <aside
          className="tl-panel p-5 sm:p-6"
          aria-label="Intended maintenance sequence"
        >
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--tl-muted)]">
            Maintenance loop
          </p>
          <ol className="mt-5 space-y-0">
            {productFlowSteps.map((step, index) => (
              <li key={step} className="flex items-center gap-4 py-2.5">
                <span className="w-7 font-mono text-xs text-[var(--tl-signal)]">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="flex-1 border-b border-[var(--tl-line)] pb-2.5 text-sm">
                  {step}
                </span>
              </li>
            ))}
          </ol>
        </aside>
      </Frame>
    </section>
  );
}
