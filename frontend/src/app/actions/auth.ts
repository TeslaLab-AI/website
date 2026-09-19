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
export async function signupUser(email: string, password: string, fullName: string) {
  const supabase = await createClient()
  const siteUrl = 
    process.env.NEXT_PUBLIC_SITE_URL || 
    (process.env.NEXT_PUBLIC_VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.NEXT_PUBLIC_VERCEL_PROJECT_PRODUCTION_URL}` : null) ||
    (process.env.NEXT_PUBLIC_VERCEL_URL ? `https://${process.env.NEXT_PUBLIC_VERCEL_URL}` : null) || 
    'http://localhost:3000'

  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: {
        full_name: fullName,
      },
      emailRedirectTo: `${siteUrl}/auth/confirm`,
    },
  })

  if (error) {
    return { error: error.message }
  }

  // Provisioning
  // Because email confirmation is enabled, the user is not authenticated yet.
  // We use the admin client (Service Role) to bypass RLS for provisioning.
  if (data?.user) {
    // Prevent provisioning if Supabase returned a fake user (email already exists)
    const isFakeUser = data.user.identities && data.user.identities.length === 0
    if (isFakeUser) {
      return { error: 'This email is already registered. Please log in.' }
    }

    try {
      const adminClient = createAdminClient()
      
      // 1. Insert Profile
      const { error: profileError } = await adminClient
        .from('profiles')
        .insert({
          id: data.user.id,
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
          user_id: data.user.id,
        })

      if (memberError) {
        console.error('Failed to assign user to workspace:', memberError)
        return { error: 'Account created, but workspace assignment failed.' }
      }

    } catch (provisioningError: unknown) {
      // Log server-side to diagnose partial failures
      console.error('Provisioning failed for user', data.user.id, ':', provisioningError)
      // Propagate a generic safe error to the client
      return { error: provisioningError instanceof Error ? provisioningError.message : 'Failed to provision initial account data.' }
    }
  }

  return { data }
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
