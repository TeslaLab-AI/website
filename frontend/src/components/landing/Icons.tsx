/**
 * Purpose:
 * Inline geometric icons for landing-page sections.
 *
 * Responsibilities:
 * - Give each capability and flow step a distinct visual mark.
 * - Avoid stock images or third-party icon packages.
 */

export function IconBugs() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10" aria-hidden="true">
      <circle cx="24" cy="24" r="9" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <path d="M24 8v7M24 33v7M8 24h7M33 24h7M12 12l5 5M31 31l5 5M36 12l-5 5M17 31l-5 5" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

export function IconDeps() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10" aria-hidden="true">
      <rect x="8" y="10" width="20" height="12" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <rect x="20" y="26" width="20" height="12" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <path d="M18 22v4h12" fill="none" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

export function IconSecurity() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10" aria-hidden="true">
      <path
        d="M24 8l14 6v10c0 9-6.5 16-14 18-7.5-2-14-9-14-18V14z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
      />
      <path d="M18 24l4 4 8-9" fill="none" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

export function IconCi() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10" aria-hidden="true">
      <circle cx="24" cy="24" r="14" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <path d="M20 16l12 8-12 8z" fill="currentColor" />
    </svg>
  );
}

export function IconTest() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10" aria-hidden="true">
      <path d="M14 10h20v28H14z" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <path d="M20 20h8M20 26h8M20 32l3 3 7-8" fill="none" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}
