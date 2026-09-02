/**
 * Purpose:
 * Lists the maintenance problem classes TeslaLab is designed to handle.
 *
 * Responsibilities:
 * - Describe intended capability areas without fabricated coverage claims.
 */

import { capabilities } from "./content";
import { Frame } from "./Frame";

export function Capabilities() {
  return (
    <section className="py-6" aria-labelledby="capabilities-heading">
      <div className="tl-rule" />
      <Frame className="py-20">
        <p className="tl-kicker">Capabilities</p>
        <h2
          id="capabilities-heading"
          className="mt-3 max-w-xl text-3xl font-semibold tracking-[-0.03em]"
        >
          The routine work that keeps software healthy.
        </h2>
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {capabilities.map((item, index) => (
            <li key={item.title} className="tl-panel flex flex-col p-5">
              <span className="font-mono text-[0.68rem] text-[var(--tl-muted)]">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-8 text-lg font-semibold">{item.title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-[var(--tl-muted)]">
                {item.detail}
              </p>
            </li>
          ))}
        </ul>
      </Frame>
    </section>
  );
}
