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
        <div className="tl-paper px-6 py-14 sm:px-12 sm:py-16">
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
            Create an account to connect GitHub from the dashboard. GitHub App
            installation is the next step after you sign in.
          </p>
          <Link
            href="/register"
            className="mt-8 inline-flex min-h-11 items-center bg-[#101114] px-5 text-sm font-medium text-[#efe8dc] hover:bg-[#2a2c31] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#101114]"
          >
            Get started
          </Link>
        </div>
      </Frame>
    </section>
  );
}
