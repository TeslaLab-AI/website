/**
 * Purpose:
 * Shared dashboard control that starts GitHub App installation.
 *
 * Responsibilities:
 * - Submit the authenticated startGitHubInstall server action.
 * - Keep both dashboard Connect GitHub buttons on one implementation.
 */

import { startGitHubInstall } from '@/app/actions/github'

type ConnectGitHubButtonProps = {
  label: string
  disabled?: boolean
  className: string
  children?: React.ReactNode
}

export function ConnectGitHubButton({
  label,
  disabled = false,
  className,
  children,
}: ConnectGitHubButtonProps) {
  return (
    <form action={startGitHubInstall}>
      <button type="submit" disabled={disabled} className={className}>
        {children}
        {label}
      </button>
    </form>
  )
}
