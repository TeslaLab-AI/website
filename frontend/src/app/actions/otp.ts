'use server'

/**
 * Server Actions for MSG91 Phone Registration OTP:
 * - Dispatches send and verify OTP requests to the backend API.
 * - Handles 1-minute expiration and 3-chance lockout / 1-hour block responses.
 */

function getBackendUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000'
}

export type SendOtpResult = {
  success?: boolean
  error?: string
  phone?: string
  expiresInSeconds?: number
  maxAttempts?: number
  blocked?: boolean
}

export type VerifyOtpResult = {
  success?: boolean
  error?: string
  phone?: string
  verificationToken?: string
  blocked?: boolean
  attemptsRemaining?: number
}

export async function sendOtpAction(phone: string): Promise<SendOtpResult> {
  const backendUrl = getBackendUrl().replace(/\/$/, '')

  try {
    const res = await fetch(`${backendUrl}/api/auth/otp/send`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ phone }),
      cache: 'no-store',
    })

    const data = await res.json()

    if (!res.ok) {
      return {
        error: data.detail || 'Failed to send OTP. Please verify your phone number.',
        blocked: res.status === 429,
      }
    }

    return {
      success: true,
      phone: data.phone,
      expiresInSeconds: data.expires_in_seconds || 60,
      maxAttempts: data.max_attempts || 3,
    }
  } catch (err: unknown) {
    console.error('sendOtpAction error:', err)
    return {
      error: 'Unable to connect to the backend server. Please verify the backend is running.',
    }
  }
}

export async function verifyOtpAction(phone: string, otp: string): Promise<VerifyOtpResult> {
  const backendUrl = getBackendUrl().replace(/\/$/, '')

  try {
    const res = await fetch(`${backendUrl}/api/auth/otp/verify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ phone, otp }),
      cache: 'no-store',
    })

    const data = await res.json()

    if (!res.ok) {
      const isBlocked = res.status === 403 || res.status === 429
      let attemptsRemaining: number | undefined
      
      if (data.detail && typeof data.detail === 'string') {
        const match = data.detail.match(/(\d+)\s+chance\(s\)\s+remaining/)
        if (match) {
          attemptsRemaining = parseInt(match[1], 10)
        }
      }

      return {
        error: data.detail || 'Verification failed. Please check the OTP entered.',
        blocked: isBlocked,
        attemptsRemaining,
      }
    }

    return {
      success: true,
      phone: data.phone,
      verificationToken: data.verification_token,
    }
  } catch (err: unknown) {
    console.error('verifyOtpAction error:', err)
    return {
      error: 'Unable to connect to the backend server. Please verify the backend is running.',
    }
  }
}

export async function checkPhoneStatusAction(phone: string) {
  const backendUrl = getBackendUrl().replace(/\/$/, '')

  try {
    const res = await fetch(`${backendUrl}/api/auth/otp/status?phone=${encodeURIComponent(phone)}`, {
      method: 'GET',
      cache: 'no-store',
    })

    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}
