'use client'

import { useState } from 'react'
import { signupUser } from '@/app/actions/auth'

export default function RegisterPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError(null)
    setSuccess(false)

    const formData = new FormData(event.currentTarget)
    const fullName = formData.get('fullName') as string
    const email = formData.get('email') as string
    const password = formData.get('password') as string

    // Basic client-side validation
    if (!fullName || !email || !password) {
      setError('All fields are required.')
      setLoading(false)
      return
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters.')
      setLoading(false)
      return
    }

    try {
      await signupUser(email, password, fullName)
      setSuccess(true)
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('An unexpected error occurred during signup.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col min-h-screen items-center justify-center bg-zinc-50 dark:bg-black p-4 font-sans">
      <main className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl shadow-xl overflow-hidden border border-zinc-200 dark:border-zinc-800">
        <div className="p-8">
          <h1 className="text-2xl font-bold text-zinc-900 dark:text-white mb-2">Create an account</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-8">
            Sign up for TeslaLab AI to automate your repository maintenance.
          </p>

          {success ? (
            <div className="bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 p-4 rounded-lg mb-6 border border-green-200 dark:border-green-800">
              <p className="font-medium">Check your email</p>
              <p className="text-sm mt-1">We sent a verification link to your email address. Please verify to continue.</p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <div className="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 p-3 rounded-lg text-sm border border-red-200 dark:border-red-800">
                  {error}
                </div>
              )}

              <div className="space-y-1.5">
                <label htmlFor="fullName" className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Full Name
                </label>
                <input
                  id="fullName"
                  name="fullName"
                  type="text"
                  required
                  autoComplete="name"
                  className="w-full px-3 py-2 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-800 dark:text-white sm:text-sm"
                  placeholder="John Doe"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="email" className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Email Address
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  className="w-full px-3 py-2 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-800 dark:text-white sm:text-sm"
                  placeholder="john@example.com"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password" className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Password
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  required
                  autoComplete="new-password"
                  minLength={6}
                  className="w-full px-3 py-2 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-800 dark:text-white sm:text-sm"
                  placeholder="Enter your password"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full flex justify-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? 'Signing up...' : 'Sign Up'}
              </button>
            </form>
          )}
        </div>
      </main>
    </div>
  )
}
