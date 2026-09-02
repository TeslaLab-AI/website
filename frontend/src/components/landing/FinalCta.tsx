/**
 * Purpose:
 * Closes the landing page with the Stage 0 get-started call to action.
 *
 * Responsibilities:
 * - Restate the intended operating model.
 * - Send new users to registration.
 */

import Link from "next/link";
import { Frame } from "./Frame";

export function FinalCta() {
  return (
    <section className="pb-20" aria-labelledby="final-cta-heading">
      <Frame>
        <div className="tl-paper grid gap-10 px-6 py-12 sm:px-12 sm:py-16 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
          <div>
            <p className="font-mono text-[0.72rem] uppercase tracking-[0.22em] text-[#b42318]">
              Get started
            </p>
            <h2
              id="final-cta-heading"
              className="mt-4 max-w-2xl text-3xl font-semibold tracking-[-0.03em] sm:text-4xl"
            >
              Connect once. Configure once. TeslaLab continuously maintains the
              software.
            </h2>
            <p className="mt-5 max-w-lg text-sm leading-relaxed text-[#5c574e]">
              Create an account, then connect GitHub from the dashboard.
            </p>
            <Link
              href="/register"
              className="mt-8 inline-flex min-h-11 items-center bg-[#101114] px-5 text-sm font-medium text-[#efe8dc] hover:bg-[#2a2c31] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#101114]"
            >
              Get started
            </Link>
          </div>
          <ol className="space-y-3 text-sm" aria-label="Getting started">
            <li className="flex items-center gap-4 border border-[#101114]/15 bg-white/40 px-4 py-4">
              <span className="flex h-8 w-8 items-center justify-center bg-[#101114] font-mono text-xs text-[#efe8dc]">
                01
              </span>
              Create an account
            </li>
            <li className="flex items-center gap-4 border border-[#101114]/15 bg-white/40 px-4 py-4">
              <span className="flex h-8 w-8 items-center justify-center bg-[#101114] font-mono text-xs text-[#efe8dc]">
                02
              </span>
              Connect GitHub
            </li>
            <li className="flex items-center gap-4 border border-[#101114]/15 bg-white/40 px-4 py-4">
              <span className="flex h-8 w-8 items-center justify-center bg-[#ff5e3a] font-mono text-xs text-[#1a0906]">
                03
              </span>
              Review pull requests
            </li>
          </ol>
        </div>
      </Frame>
    </section>
  );
}
