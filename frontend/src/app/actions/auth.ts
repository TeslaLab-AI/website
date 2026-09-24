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

  let user = data?.user
  let session = data?.session

  if (error) {
    const isRateLimit =
      error.status === 429 ||
      error.code === 'over_email_send_rate_limit' ||
      error.message.toLowerCase().includes('rate limit')

    if (isRateLimit) {
      // Security Guard: Admin user creation fallback is strictly restricted to local development mode.
      // In production, rate limit errors fail safely and return a clear user error without invoking privileged admin APIs.
      if (process.env.NODE_ENV === 'development') {
        try {
          const adminClient = createAdminClient()
          const { data: adminUserData, error: adminUserError } = await adminClient.auth.admin.createUser({
            email,
            password,
            email_confirm: true,
            user_metadata: { full_name: fullName },
          })

          if (adminUserError) {
            if (adminUserError.message.includes('already registered') || adminUserError.message.includes('already been registered')) {
              return { error: 'This email is already registered. Please log in.' }
            }
            return { error: adminUserError.message }
          }

          if (adminUserData?.user) {
            user = adminUserData.user
            // Log the newly created user in to set session cookies
            const { data: signInData } = await supabase.auth.signInWithPassword({ email, password })
            session = signInData?.session || null
          }
        } catch (adminErr: unknown) {
          console.error('Admin signup fallback failed:', adminErr)
          return { error: error.message }
        }
      } else {
        return {
          error: 'Email rate limit exceeded. Please wait a few minutes before trying again.',
        }
      }
    } else {
      return { error: error.message }
    }
  }

  // Provisioning
  if (user) {
    // Prevent provisioning if Supabase returned a fake user (email already exists)
    const isFakeUser = user.identities && user.identities.length === 0
    if (isFakeUser) {
      return { error: 'This email is already registered. Please log in.' }
    }

    try {
      const adminClient = createAdminClient()
      
      // 1. Upsert Profile (idempotent in case profile trigger exists or user re-signed up)
      const { error: profileError } = await adminClient
        .from('profiles')
        .upsert({
          id: user.id,
          full_name: fullName,
        }, { onConflict: 'id' })
      
      if (profileError) {
        console.error('Failed to provision profile:', profileError)
        return { error: `Account created, but profile provisioning failed: ${profileError.message}` }
      }

      // 2. Provision Workspace & Membership (idempotent check)
      const { data: existingMember } = await adminClient
        .from('workspace_members')
        .select('workspace_id')
        .eq('user_id', user.id)
        .maybeSingle()

      if (!existingMember) {
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
          return { error: `Account created, but workspace provisioning failed: ${workspaceError?.message}` }
        }

        const { error: memberError } = await adminClient
          .from('workspace_members')
          .insert({
            workspace_id: workspace.id,
            user_id: user.id,
          })

        if (memberError) {
          console.error('Failed to assign user to workspace:', memberError)
          return { error: `Account created, but workspace assignment failed: ${memberError.message}` }
        }
      }

    } catch (provisioningError: unknown) {
      console.error('Provisioning failed for user', user.id, ':', provisioningError)
      return { error: provisioningError instanceof Error ? provisioningError.message : 'Failed to provision initial account data.' }
    }

    // If the user has an active session, redirect straight to dashboard
    if (session) {
      redirect('/dashboard')
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

/**
 * Persists user onboarding profile selection (user_type).
 * Updates public.profiles and user_metadata in Supabase Auth.
 */
export async function saveOnboardingUserType(userType: string) {
  const validTypes = ['startup', 'agency', 'freelancer', 'others']
  if (!userType || !validTypes.includes(userType)) {
    return { error: 'Invalid user type selected.' }
  }

  const supabase = await createClient()
  const { data: { user }, error: userError } = await supabase.auth.getUser()

  if (userError || !user) {
    return { error: 'Unauthenticated. Please log in again.' }
  }

  // 1. Update public.profiles table
  const { error: profileError } = await supabase
    .from('profiles')
    .update({
      user_type: userType,
      updated_at: new Date().toISOString(),
    })
    .eq('id', user.id)

  if (profileError) {
    console.error('Failed to save onboarding user_type in profiles:', profileError)
    return { error: 'Failed to update user profile. Please try again.' }
  }

  // 2. Synchronize Supabase Auth user metadata
  await supabase.auth.updateUser({
    data: { user_type: userType },
  })

  return { success: true }
}
