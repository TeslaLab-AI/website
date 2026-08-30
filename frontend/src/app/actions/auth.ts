'use server'
// The 'use server' directive marks all exports in this file as Server Actions.
// Signup is implemented as a Server Action to securely instantiate the Supabase
// client and manage cookies exclusively on the server, avoiding client-side secrets.

import { createClient } from '@/utils/supabase/server'

/**
 * Minimal signup function using Supabase Auth.
 *
 * Notes:
 * - `full_name` is initially stored in Supabase Auth's user metadata for simplicity.
 * - This function is strictly the authentication/signup unit. The creation of a 
 *   corresponding profile record in application tables will be handled separately.
 */
export async function signupUser(email: string, password: string, fullName: string) {
  const supabase = await createClient()

  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: {
        full_name: fullName,
      },
    },
  })

  if (error) {
    throw new Error(error.message)
  }

  return data
}

/**
 * Minimal login function using Supabase Auth.
 * Authenticates the user and manages cookies securely on the server.
 */
export async function loginUser(email: string, password: string) {
  const supabase = await createClient()

  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })

  if (error) {
    throw new Error(error.message)
  }

  return data
}
