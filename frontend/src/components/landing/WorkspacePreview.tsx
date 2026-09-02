/**
 * Purpose:
 * Renders a visual product-preview of the TeslaLab workspace.
 *
 * Responsibilities:
 * - Show how findings and a pull request would appear in the product.
 * - Remain a labeled preview, not fabricated customer evidence.
 */

export function WorkspacePreview() {
  return (
    <div
      className="tl-console overflow-hidden shadow-[0_24px_80px_rgba(0,0,0,0.45)]"
      aria-label="TeslaLab workspace preview"
    >
      <div className="flex items-center gap-2 border-b border-[var(--tl-line)] px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5e3a]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#c4b8a8]/50" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#c4b8a8]/30" />
        <p className="ml-3 font-mono text-[0.65rem] tracking-[0.16em] text-[var(--tl-muted)]">
          TESLALAB · WORKSPACE PREVIEW
        </p>
      </div>
      <div className="grid md:grid-cols-[9.5rem_minmax(0,1fr)]">
        <div className="hidden border-r border-[var(--tl-line)] p-4 md:block">
          <p className="font-mono text-[0.62rem] uppercase tracking-[0.18em] text-[var(--tl-muted)]">
            Repository
          </p>
          <div className="mt-4 space-y-2 text-xs">
            <div className="h-2 w-16 bg-[var(--tl-signal)]" />
            <p className="font-mono text-[var(--tl-fg)]">owner / repo</p>
            <p className="text-[var(--tl-muted)]">main</p>
          </div>
          <div className="mt-8 space-y-2">
            <div className="h-1.5 w-full bg-[var(--tl-line)]" />
            <div className="h-1.5 w-3/4 bg-[var(--tl-line)]" />
            <div className="h-1.5 w-1/2 bg-[var(--tl-line)]" />
          </div>
        </div>
        <div className="p-4 sm:p-5">
          <p className="font-mono text-[0.62rem] uppercase tracking-[0.18em] text-[var(--tl-muted)]">
            Findings
          </p>
          <ul className="mt-4 space-y-3">
            <li className="flex items-center gap-3 border border-[var(--tl-line)] bg-black/20 px-3 py-3">
              <span className="h-8 w-1 bg-[var(--tl-signal)]" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Bug</p>
                <p className="truncate font-mono text-[0.7rem] text-[var(--tl-muted)]">
                  src/api/handler.ts
                </p>
              </div>
              <span className="font-mono text-[0.65rem] text-[var(--tl-signal)]">OPEN</span>
            </li>
            <li className="flex items-center gap-3 border border-[var(--tl-line)] bg-black/20 px-3 py-3">
              <span className="h-8 w-1 bg-[#d4b483]" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Dependency</p>
                <p className="truncate font-mono text-[0.7rem] text-[var(--tl-muted)]">
                  package.json
                </p>
              </div>
              <span className="font-mono text-[0.65rem] text-[var(--tl-muted)]">PLAN</span>
            </li>
            <li className="flex items-center gap-3 border border-[var(--tl-line)] bg-black/20 px-3 py-3">
              <span className="h-8 w-1 bg-[#7d9b6a]" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Validation</p>
                <p className="truncate font-mono text-[0.7rem] text-[var(--tl-muted)]">
                  tests · build · review
                </p>
              </div>
              <span className="font-mono text-[0.65rem] text-[#7d9b6a]">PR</span>
            </li>
          </ul>
          <div className="mt-4 border border-[var(--tl-line)] p-3">
            <p className="font-mono text-[0.62rem] uppercase tracking-[0.16em] text-[var(--tl-muted)]">
              Draft change
            </p>
            <div className="mt-3 space-y-1.5" aria-hidden="true">
              <div className="flex h-2 overflow-hidden">
                <span className="w-2/3 bg-[#2d4a38]" />
                <span className="w-1/3 bg-[#5a2420]" />
              </div>
              <div className="flex h-2 overflow-hidden">
                <span className="w-1/2 bg-[#2d4a38]" />
                <span className="w-1/4 bg-[#5a2420]" />
              </div>
              <div className="flex h-2 overflow-hidden">
                <span className="w-3/4 bg-[#2d4a38]" />
              </div>
            </div>
            <p className="mt-3 text-xs text-[var(--tl-muted)]">
              Lands as a pull request. A human still merges.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
