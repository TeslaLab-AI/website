'use server'
// The 'use server' directive marks all exports in this file as Server Actions.
// Signup is implemented as a Server Action to securely instantiate the Supabase
// client and manage cookies exclusively on the server, avoiding client-side secrets.

import { createClient } from '@/utils/supabase/server'
import { createAdminClient } from '@/utils/supabase/admin'
import { redirect } from 'next/navigation'

/**
 * Minimal signup function using Supabase Auth.
 *
 * Notes:
 * - `full_name` is initially stored in Supabase Auth's user metadata for simplicity.
 * - Profile and workspace provisioning are handled sequentially after a successful auth creation.
 */
export async function signupUser(email: string, password: string, fullName: string, phone?: string) {
  const supabase = await createClient()

  try {
    const adminClient = createAdminClient()

    // Create user directly with email_confirm: true so Supabase never sends a confirmation email
    const { data: adminData, error: createError } = await adminClient.auth.admin.createUser({
      email,
      password,
      email_confirm: true,
      user_metadata: {
        full_name: fullName,
        ...(phone ? { phone } : {}),
      },
    })

    if (createError) {
      if (createError.message.toLowerCase().includes('already been registered') || createError.message.toLowerCase().includes('already registered')) {
        return { error: 'This email is already registered. Please log in.' }
      }
      if (createError.message.toLowerCase().includes('fetch failed') || createError.message.includes('Failed to fetch')) {
        return { error: 'Unable to reach Supabase. Please configure your actual Supabase URL and keys in frontend/.env.local.' }
      }
      return { error: createError.message }
    }

    const user = adminData.user
    if (!user) {
      return { error: 'Failed to create user account.' }
    }

    // 1. Insert Profile
    const { error: profileError } = await adminClient
      .from('profiles')
      .insert({
        id: user.id,
        full_name: fullName,
      })

    if (profileError) {
      console.error('Failed to provision profile:', profileError)
      return { error: 'Account created, but profile provisioning failed.' }
    }

    // 2. Insert Workspace
    const { data: workspace, error: workspaceError } = await adminClient
      .from('workspaces')
      .insert({
        name: `${fullName}'s Workspace`,
        plan: 'free',
      })
      .select('id')
      .single()

    if (workspaceError || !workspace) {
      console.error('Failed to provision workspace:', workspaceError)
      return { error: 'Account created, but workspace provisioning failed.' }
    }

    // 3. Insert Workspace Member
    const { error: memberError } = await adminClient
      .from('workspace_members')
      .insert({
        workspace_id: workspace.id,
        user_id: user.id,
      })

    if (memberError) {
      console.error('Failed to assign user to workspace:', memberError)
      return { error: 'Account created, but workspace assignment failed.' }
    }

    // Automatically sign the user in so session cookies are set for direct dashboard access
    const { data: signInData, error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (signInError) {
      console.error('Post-signup sign-in error:', signInError)
      return { error: signInError.message }
    }

    return { data: signInData }
  } catch (err: unknown) {
    console.error('Signup error:', err)
    if (err instanceof Error) {
      return { error: err.message }
    }
    return { error: 'An unexpected error occurred during signup.' }
  }
}

/**
 * Minimal login function using Supabase Auth.
 * Authenticates the user and manages cookies securely on the server.
 */
export async function loginUser(email: string, password: string) {
  try {
    const supabase = await createClient()

    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (error) {
      if (error.message.toLowerCase().includes('fetch failed') || error.message.includes('Failed to fetch')) {
        return { error: 'Unable to reach Supabase. Please configure your actual Supabase URL and Anon Key in frontend/.env.local.' }
      }
      return { error: error.message }
    }

    return { data }
  } catch (err: unknown) {
    console.error('Login action error:', err)
    if (err instanceof Error) {
      if (err.message.includes('fetch failed') || err.message.includes('ENOTFOUND') || err.message.includes('your-project')) {
        return { error: 'Unable to reach Supabase. Please configure your actual Supabase URL and Anon Key in frontend/.env.local.' }
      }
      return { error: err.message }
    }
    return { error: 'An unexpected error occurred during login.' }
  }
}

/**
 * Minimal logout function using Supabase Auth.
 * Clears the session on the server and redirects to login.
 */
export async function logoutUser() {
  const supabase = await createClient()
  const { error } = await supabase.auth.signOut()
  
  if (error) {
    console.error('Logout error:', error)
  }
  
  redirect('/login')
}
