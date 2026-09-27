'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { signupUser } from '@/app/actions/auth'
import { sendOtpAction, verifyOtpAction } from '@/app/actions/otp'

export default function RegisterPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form fields
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [phone, setPhone] = useState('')

  // OTP state
  const [otp, setOtp] = useState('')
  const [otpSent, setOtpSent] = useState(false)
  const [otpVerified, setOtpVerified] = useState(false)
  const [verificationToken, setVerificationToken] = useState<string | null>(null)
  const [otpSending, setOtpSending] = useState(false)
  const [otpVerifying, setOtpVerifying] = useState(false)
  const [otpError, setOtpError] = useState<string | null>(null)
  const [otpSuccess, setOtpSuccess] = useState<string | null>(null)

  // 1-minute (60 seconds) timer & 3-chance lockout
  const [timer, setTimer] = useState(60)
  const [timerActive, setTimerActive] = useState(false)
  const [chancesLeft, setChancesLeft] = useState(3)
  const [isBlocked, setIsBlocked] = useState(false)
  const [blockMessage, setBlockMessage] = useState<string | null>(null)

  // 1-minute countdown timer effect
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null
    if (timerActive && timer > 0) {
      interval = setInterval(() => {
        setTimer((prev) => prev - 1)
      }, 1000)
    } else if (timer === 0 && timerActive) {
      setTimerActive(false)
      setOtpError('OTP has expired after 1 minute. Please click Resend OTP to request a new code.')
    }
    return () => {
      if (interval) clearInterval(interval)
    }
  }, [timerActive, timer])

  // Format timer as MM:SS
  const formatTimer = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  // Handle Send / Resend OTP
  async function handleSendOtp() {
    if (!phone || phone.trim().length < 10) {
      setOtpError('Please enter a valid phone number (at least 10 digits).')
      return
    }

    setOtpSending(true)
    setOtpError(null)
    setOtpSuccess(null)

    try {
      const res = await sendOtpAction(phone.trim())
      if (res.error) {
        if (res.blocked) {
          setIsBlocked(true)
          setBlockMessage(res.error)
        } else {
          setOtpError(res.error)
        }
      } else {
        setOtpSent(true)
        setTimer(res.expiresInSeconds || 60)
        setTimerActive(true)
        setChancesLeft(res.maxAttempts || 3)
        setOtpSuccess('OTP sent via SMS. Please enter the code within 1 minute.')
        setOtp('')
      }
    } catch {
      setOtpError('Failed to send OTP. Please check that the backend server is running.')
    } finally {
      setOtpSending(false)
    }
  }

  // Handle Verify OTP
  async function handleVerifyOtp() {
    if (!otp || otp.trim().length < 4) {
      setOtpError('Please enter the OTP received on your phone.')
      return
    }

    if (timer === 0) {
      setOtpError('This OTP has expired. Please request a new OTP.')
      return
    }

    setOtpVerifying(true)
    setOtpError(null)
    setOtpSuccess(null)

    try {
      const res = await verifyOtpAction(phone.trim(), otp.trim())
      if (res.error) {
        if (res.blocked) {
          setIsBlocked(true)
          setBlockMessage(res.error)
          setTimerActive(false)
          setOtpError(null)
        } else {
          if (res.attemptsRemaining !== undefined) {
            setChancesLeft(res.attemptsRemaining)
          }
          setOtpError(res.error)
        }
      } else {
        setOtpVerified(true)
        setVerificationToken(res.verificationToken || '')
        setTimerActive(false)
        setOtpSuccess('Phone number verified successfully!')
        setOtpError(null)
      }
    } catch {
      setOtpError('Verification failed due to a network error.')
    } finally {
      setOtpVerifying(false)
    }
  }

  // Handle form submission
  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError(null)

    // Basic client-side validation
    if (!fullName || !email || !password || !phone) {
      setError('All fields including phone number are required.')
      setLoading(false)
      return
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters.')
      setLoading(false)
      return
    }

    if (!otpVerified) {
      setError('Please verify your phone number via OTP before completing registration.')
      setLoading(false)
      return
    }

    try {
      const result = await signupUser(email, password, fullName, phone)
      if (result?.error) {
        setError(result.error)
        setLoading(false)
      } else {
        router.push('/dashboard')
        router.refresh()
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('An unexpected error occurred during signup.')
      }
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col min-h-screen items-center justify-center bg-zinc-50 dark:bg-black p-4 font-sans">
      <main className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl shadow-xl overflow-hidden border border-zinc-200 dark:border-zinc-800">
        <div className="p-8">
          <h1 className="text-2xl font-bold text-zinc-900 dark:text-white mb-2">Create an account</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
            Sign up for TeslaLab AI to automate your repository maintenance.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 p-3 rounded-lg text-sm border border-red-200 dark:border-red-800">
                {error}
              </div>
            )}

              {/* 1-Hour Block Warning */}
              {isBlocked && (
                <div className="bg-red-100 dark:bg-red-900/50 text-red-800 dark:text-red-200 p-3.5 rounded-lg text-sm border border-red-300 dark:border-red-700 font-medium">
                  {blockMessage || 'You have exceeded 3 incorrect OTP attempts. This phone number is blocked from registration for 1 hour.'}
                </div>
              )}

              {/* Full Name */}
              <div className="space-y-1">
                <label htmlFor="fullName" className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Full Name
                </label>
                <input
                  id="fullName"
                  name="fullName"
                  type="text"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  autoComplete="name"
                  className="w-full px-3 py-2 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-800 dark:text-white sm:text-sm"
                  placeholder="John Doe"
                />
              </div>

              {/* Email Address */}
              <div className="space-y-1">
                <label htmlFor="email" className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Email Address
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  className="w-full px-3 py-2 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-800 dark:text-white sm:text-sm"
                  placeholder="john@example.com"
                />
              </div>

              {/* Password */}
              <div className="space-y-1">
                <label htmlFor="password" className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Password
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  minLength={6}
                  className="w-full px-3 py-2 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-800 dark:text-white sm:text-sm"
                  placeholder="Enter your password (min 6 characters)"
                />
              </div>

              {/* Phone Number & OTP Section */}
              <div className="pt-2 border-t border-zinc-200 dark:border-zinc-800 space-y-2">
                <label htmlFor="phone" className="text-sm font-medium text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                  <span>Phone Number (for SMS OTP)</span>
                  {otpVerified && (
                    <span className="text-xs bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300 font-semibold px-2 py-0.5 rounded-full">
                      Verified ✓
                    </span>
                  )}
                </label>
                <div className="flex gap-2">
                  <input
                    id="phone"
                    name="phone"
                    type="tel"
                    required
                    disabled={otpVerified || isBlocked}
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+91 9876543210"
                    className="flex-1 px-3 py-2 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-800 dark:text-white sm:text-sm disabled:opacity-60"
                  />
                  <button
                    type="button"
                    onClick={handleSendOtp}
                    disabled={otpSending || otpVerified || isBlocked || (timerActive && timer > 0)}
                    className="px-3 py-2 bg-zinc-800 hover:bg-zinc-700 dark:bg-zinc-700 dark:hover:bg-zinc-600 text-white text-xs font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {otpSending
                      ? 'Sending...'
                      : timerActive && timer > 0
                      ? `Resend in ${timer}s`
                      : otpSent
                      ? 'Resend OTP'
                      : 'Send OTP'}
                  </button>
                </div>

                {/* OTP Input and Verification Controls */}
                {otpSent && !otpVerified && !isBlocked && (
                  <div className="bg-zinc-50 dark:bg-zinc-800/60 p-3 rounded-lg border border-zinc-200 dark:border-zinc-700/60 space-y-2.5 mt-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-600 dark:text-zinc-400">
                        Timer: <strong className="text-blue-600 dark:text-blue-400 font-mono">{formatTimer(timer)}</strong>
                      </span>
                      <span className={`font-medium ${chancesLeft <= 1 ? 'text-red-600 dark:text-red-400' : 'text-zinc-500 dark:text-zinc-400'}`}>
                        Chances remaining: {chancesLeft}/3
                      </span>
                    </div>

                    <div className="flex gap-2">
                      <input
                        type="text"
                        maxLength={8}
                        value={otp}
                        onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                        placeholder="Enter 6-digit OTP"
                        disabled={timer === 0 || otpVerifying}
                        className="flex-1 px-3 py-1.5 border border-zinc-300 dark:border-zinc-600 rounded-lg text-sm text-center tracking-widest font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-900 dark:text-white"
                      />
                      <button
                        type="button"
                        onClick={handleVerifyOtp}
                        disabled={otpVerifying || timer === 0 || otp.trim().length === 0}
                        className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium rounded-lg disabled:opacity-50 transition-colors"
                      >
                        {otpVerifying ? 'Checking...' : 'Verify OTP'}
                      </button>
                    </div>

                    {otpError && (
                      <p className="text-xs text-red-600 dark:text-red-400 font-medium">
                        {otpError}
                      </p>
                    )}
                    {otpSuccess && (
                      <p className="text-xs text-green-600 dark:text-green-400 font-medium">
                        {otpSuccess}
                      </p>
                    )}
                  </div>
                )}

                {otpVerified && (
                  <p className="text-xs text-green-600 dark:text-green-400 font-medium">
                    Phone verified successfully! You can now proceed with account creation.
                  </p>
                )}
              </div>

              {/* Submit Button */}
              <button
                type="submit"
                disabled={loading || !otpVerified || isBlocked}
                className="w-full mt-2 flex justify-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {loading
                  ? 'Signing up...'
                  : !otpVerified
                  ? 'Verify phone to sign up'
                  : 'Sign Up'}
              </button>
            </form>

          <div className="mt-6 text-center text-xs text-zinc-500 dark:text-zinc-400">
            Already have an account?{' '}
            <a href="/login" className="text-blue-600 dark:text-blue-400 hover:underline">
              Log in
            </a>
          </div>
        </div>
      </main>
    </div>
  )
}
