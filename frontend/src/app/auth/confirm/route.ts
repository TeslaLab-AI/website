import { type EmailOtpType } from '@supabase/supabase-js'
import { NextRequest, NextResponse } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const token_hash = searchParams.get('token_hash')
  const type = searchParams.get('type') as EmailOtpType | null
  let next = searchParams.get('next') ?? '/dashboard'

  if (!next.startsWith('/') || next.startsWith('//')) {
    next = '/dashboard'
  }

  const redirectUrl = new URL(next, request.url)

  if (token_hash && type) {
    const cookieStore = await cookies()
    const response = NextResponse.redirect(redirectUrl)

    const url = process.env.NEXT_PUBLIC_SUPABASE_URL
    const anonKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

    if (!url || !anonKey) {
      return NextResponse.redirect(new URL('/login?error=Missing+auth+configuration', request.url))
    }

    const supabase = createServerClient(url, anonKey, {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet: Array<{ name: string; value: string; options?: Record<string, unknown> }>) {
          cookiesToSet.forEach(({ name, value, options }) => {
            try {
              cookieStore.set(name, value, options)
            } catch {
              // ignore if called in immutable context
            }
            response.cookies.set(name, value, options)
          })
        },
      },
    })

    const { error } = await supabase.auth.verifyOtp({
      type,
      token_hash,
    })

    if (!error) {
      return response
    } else {
      return NextResponse.redirect(
        new URL('/login?error=Email+link+is+invalid+or+has+expired.+If+you+already+verified,+please+try+logging+in.', request.url)
      )
    }
  }

  return NextResponse.redirect(new URL('/login?error=Could+not+verify+email', request.url))
}
