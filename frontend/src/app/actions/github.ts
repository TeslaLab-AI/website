/**
 * Purpose:
 * Starts GitHub App installation from an authenticated TeslaLab session.
 *
 * Responsibilities:
 * - Require a server-validated Supabase user.
 * - Forward the user's access token to FastAPI.
 * - Redirect the browser to the GitHub App installation URL returned by the backend.
 */

'use server'

import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'

export async function startGitHubInstall() {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session?.access_token) {
    redirect('/login')
  }

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000'

  let response: Response
  try {
    response = await fetch(`${backendUrl}/api/github/install/start`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session.access_token}`,
      },
      redirect: 'manual',
    })
  } catch {
    redirect('/dashboard?connect_error=1')
  }

  if (response.status === 401) {
    redirect('/login')
  }

  const location = response.headers.get('location')
  if (
    (response.status === 302 || response.status === 303 || response.status === 307) &&
    location &&
    location.startsWith('https://github.com/apps/')
  ) {
    redirect(location)
  }

  redirect('/dashboard?connect_error=1')
}
