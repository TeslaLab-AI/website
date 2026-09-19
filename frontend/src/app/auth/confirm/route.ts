import { type EmailOtpType } from '@supabase/supabase-js'
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const token_hash = searchParams.get('token_hash')
  const type = searchParams.get('type') as EmailOtpType | null
  const next = searchParams.get('next') ?? '/dashboard'

  if (token_hash && type) {
    const supabase = await createClient()

    const { error } = await supabase.auth.verifyOtp({
      type,
      token_hash,
    })

    if (!error) {
      // Redirect user to the authenticated dashboard
      return NextResponse.redirect(new URL(next, request.url))
    } else {
      // OTP expired or already consumed (e.g. by an email scanner prefetch).
      // Redirect to login with a clear error message.
      return NextResponse.redirect(
        new URL('/login?error=Email+link+is+invalid+or+has+expired.+If+you+already+verified,+please+try+logging+in.', request.url)
      )
    }
  }

  // Missing token_hash or type — malformed confirmation link
  return NextResponse.redirect(new URL('/login?error=Could+not+verify+email', request.url))
}
