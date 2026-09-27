/**
 * Purpose:
 * Constrains landing sections to a consistent reading width.
 *
 * Responsibilities:
 * - Keep layout alignment consistent across landing sections.
 */

export function Frame({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={`tl-frame ${className}`}>{children}</div>;
}
