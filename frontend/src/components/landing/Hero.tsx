/**
 * Purpose:
 * Renders the TeslaLab landing-page hero.
 *
 * Responsibilities:
 * - States the product positioning and core message.
 * - Shows a visual workspace preview beside the primary calls to action.
 */

import Link from "next/link";
import { Frame } from "./Frame";
import { WorkspacePreview } from "./WorkspacePreview";

export function Hero() {
  return (
    <section className="relative py-16 sm:py-24" aria-labelledby="hero-heading">
      <Frame className="grid items-center gap-12 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <div>
          <p className="tl-kicker">TeslaLab AI</p>
          <h1
            id="hero-heading"
            className="mt-5 max-w-xl text-[2.7rem] font-semibold leading-[1.02] tracking-[-0.045em] sm:text-6xl"
          >
            AI engineering
            <br />
            workforce for
            <br />
            <span className="text-[var(--tl-signal)]">B2B software.</span>
          </h1>
          <p className="mt-6 max-w-md text-lg leading-relaxed text-[var(--tl-muted)]">
            Connect your repository. TeslaLab finds, investigates, and safely
            fixes routine engineering problems — then opens a pull request.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/register" className="tl-btn-primary">
              Connect GitHub
            </Link>
            <Link href="#how-it-works" className="tl-btn-ghost">
              See how it works
            </Link>
          </div>
        </div>
        <WorkspacePreview />
      </Frame>
    </section>
  );
}
