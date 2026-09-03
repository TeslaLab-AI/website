import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@/utils/supabase/server';

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const installation_id = searchParams.get('installation_id');
  const state = searchParams.get('state');
  const setup_action = searchParams.get('setup_action');

  if (!installation_id || !state) {
    return NextResponse.json({ error: 'Missing parameters' }, { status: 400 });
  }

  // Get current user session securely
  const supabase = await createClient();
  const { data: { session }, error } = await supabase.auth.getSession();

  if (error || !session) {
    // If not authenticated, redirect them to login first. 
    // They might lose the callback, but this is a security boundary.
    return NextResponse.redirect(new URL('/login', request.url));
  }

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000';

  try {
    // Authenticate the backend request using the user's secure token
    const res = await fetch(`${backendUrl}/api/github/callback`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${session.access_token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        installation_id,
        state,
        setup_action
      }),
      cache: 'no-store'
    });

    if (!res.ok) {
      const text = await res.text();
      console.error('Backend callback failed:', text);
      return NextResponse.json({ error: 'Failed to bind GitHub installation' }, { status: res.status });
    }

    // Success, redirect to dashboard
    return NextResponse.redirect(new URL('/dashboard', request.url));
  } catch (err) {
    console.error('Error during GitHub callback:', err);
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
  }
}
