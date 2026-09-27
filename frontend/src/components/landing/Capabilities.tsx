/**
 * Purpose:
 * Lists the maintenance problem classes TeslaLab is designed to handle.
 *
 * Responsibilities:
 * - Describe intended capability areas without fabricated coverage claims.
 */

import { capabilities } from "./content";
import { Frame } from "./Frame";
import { IconBugs, IconCi, IconDeps, IconSecurity, IconTest } from "./Icons";

const icons = [IconBugs, IconDeps, IconSecurity, IconCi, IconTest];

export function Capabilities() {
  return (
    <section className="py-8" aria-labelledby="capabilities-heading">
      <div className="tl-rule" />
      <Frame className="py-16">
        <p className="tl-kicker">Capabilities</p>
        <h2
          id="capabilities-heading"
          className="mt-3 max-w-xl text-3xl font-semibold tracking-[-0.03em]"
        >
          The routine work that keeps software healthy.
        </h2>
        <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {capabilities.map((item, index) => {
            const Icon = icons[index];
            return (
              <li
                key={item.title}
                className="tl-panel group min-h-[16rem] p-5 transition-colors hover:border-[var(--tl-signal)]"
              >
                <div className="text-[var(--tl-signal)]">
                  <Icon />
                </div>
                <h3 className="mt-8 text-lg font-semibold">{item.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-[var(--tl-muted)]">
                  {item.detail}
                </p>
              </li>
            );
          })}
        </ul>
      </Frame>
    </section>
  );
}
