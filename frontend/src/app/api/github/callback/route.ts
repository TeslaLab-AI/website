import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { createClient } from '@/utils/supabase/server';

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const installationId = searchParams.get('installation_id');
  const queryState = searchParams.get('state');
  const setupAction = searchParams.get('setup_action');

  if (!installationId) {
    return NextResponse.json(
      { error: 'Missing installation_id' },
      { status: 400 }
    );
  }

  // Recover state from cookie if GitHub omitted it from the redirect URL.
  const cookieStore = await cookies();
  const cookieState =
    cookieStore.get('teslalab_github_install_state')?.value;

  const state = queryState || cookieState;

  if (!state) {
    return NextResponse.json(
      { error: 'Missing installation state' },
      { status: 400 }
    );
  }

  // Get current user session securely
  const supabase = await createClient();
  const { data: { session }, error } = await supabase.auth.getSession();

  if (error || !session) {
    // If not authenticated, redirect them to login first.
    // They might lose the callback, but this is a security boundary.
    return NextResponse.redirect(new URL('/login', request.url));
  }

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;

  if (!backendUrl) {
    console.error('NEXT_PUBLIC_BACKEND_URL is not configured');
    return NextResponse.json(
      { error: 'Server configuration error' },
      { status: 500 }
    );
  }

  try {
    // Authenticate the backend request using the user's secure token
    const res = await fetch(
      `${backendUrl.replace(/\/$/, '')}/api/github/callback`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          installation_id: installationId,
          state,
          setup_action: setupAction,
        }),
        cache: 'no-store',
      }
    );

    if (!res.ok) {
      const text = await res.text();
      console.error('Backend callback failed:', text);
      return NextResponse.json({ error: 'Failed to bind GitHub installation' }, { status: res.status });
    }

    // Clear the state cookie after successful processing.
    const responseCookieStore = await cookies();
    responseCookieStore.set('teslalab_github_install_state', '', {
      httpOnly: true,
      secure: true,
      sameSite: 'lax',
      path: '/',
      maxAge: 0,
    });

    // Success, redirect to dashboard
    return NextResponse.redirect(new URL('/dashboard', request.url));
  } catch (err) {
    console.error('Error during GitHub callback:', err);
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
  }
}
