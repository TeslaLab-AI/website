/**
 * Purpose:
 * Starts GitHub App installation from an authenticated TeslaLab session.
 *
 * Responsibilities:
 * - Require a server-validated Supabase user.
 * - Forward the user's access token to FastAPI.
 * - Store the signed state in an HttpOnly cookie for the callback.
 * - Redirect the browser to the GitHub App installation URL returned by the backend.
 */

'use server'

import { cookies } from 'next/headers'
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

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL

  if (!backendUrl) {
    console.error('NEXT_PUBLIC_BACKEND_URL is not configured')
    redirect('/dashboard?connect_error=1')
  }

  let response: Response
  try {
    response = await fetch(
      `${backendUrl.replace(/\/$/, '')}/api/github/install/start`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session.access_token}`,
        },
        redirect: 'manual',
        cache: 'no-store',
      }
    )
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
    // Extract the state parameter from the GitHub installation URL
    // and persist it in an HttpOnly cookie so the callback can recover
    // it even when GitHub omits state from the redirect.
    try {
      const installUrl = new URL(location)
      const state = installUrl.searchParams.get('state')
      if (state) {
        const cookieStore = await cookies()
        cookieStore.set('teslalab_github_install_state', state, {
          httpOnly: true,
          secure: true,
          sameSite: 'lax',
          path: '/',
          maxAge: 600,
        })
      }
    } catch (err) {
      // Cookie write failure must not block the redirect.
      console.error('Failed to persist install state cookie:', err)
    }

    // redirect() throws internally — keep it outside the try/catch above.
    redirect(location)
  }

  redirect('/dashboard?connect_error=1')
}
