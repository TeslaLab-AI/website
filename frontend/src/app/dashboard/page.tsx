/**
 * Purpose:
 * Renders the primary dashboard view for the workspace.
 *
 * Responsibilities:
 * - Determine the user's workspace and GitHub installation state.
 * - If no GitHub connection exists, prompt the user to connect.
 * - If a connection exists but no repo is selected, render RepositorySelector.
 * - If a repo is selected, render the RepositoryDashboard for scanning.
 */
import { ConnectGitHubButton } from '@/components/github/ConnectGitHubButton'
import { RepositorySelector } from '@/components/github/RepositorySelector'
import { createClient } from '@/utils/supabase/server'
import Link from 'next/link'
import { RepositoryDashboard } from '@/components/github/RepositoryDashboard'
import { OnboardingScreen } from '@/components/auth/OnboardingScreen'

interface Repo {
  id: string
  name: string
  owner: string
  default_branch: string
  status?: string
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ connect_error?: string, action?: string, repo_id?: string }>
}) {
  const params = await searchParams
  const isAddingRepo = params.action === 'add_repo'

  const supabase = await createClient()

  // Verify authenticated user & check onboarding completion status
  const { data: { user } } = await supabase.auth.getUser()

  if (user) {
    const { data: profile } = await supabase
      .from('profiles')
      .select('user_type')
      .eq('id', user.id)
      .single()

    const userType = profile?.user_type || user?.user_metadata?.user_type

    if (!userType) {
      return <OnboardingScreen />
    }
  }

  const { data: workspaces } = await supabase.from('workspaces').select('*').limit(1)
  const workspace = workspaces?.[0]

  let hasGithub = false
  let selectedRepos: Repo[] = []
  let activeRepo: Repo | null = null
  
  if (workspace) {
    const { data: installations } = await supabase
      .from('github_installations')
      .select('*')
      .eq('workspace_id', workspace.id)
      .limit(1)
    hasGithub = !!(installations && installations.length > 0)
    
    if (hasGithub) {
      const { data: repos } = await supabase
        .from('repositories')
        .select('*')
        .eq('workspace_id', workspace.id)
        .eq('status', 'selected')
      
      selectedRepos = repos || []
      
      if (params.repo_id) {
        activeRepo = selectedRepos.find(r => r.id === params.repo_id) || null
      } 
      if (!activeRepo && selectedRepos.length > 0) {
        activeRepo = selectedRepos[0]
      }
    }
  }

  return (
    <div className="p-6 md:p-10 w-full max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-2xl font-bold text-zinc-900 dark:text-white">
          Repository Scan
        </h2>
        
        {selectedRepos.length > 0 && !isAddingRepo && (
          <Link 
            href="?action=add_repo"
            className="px-4 py-2 bg-blue-50 text-blue-600 hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50 rounded-lg text-sm font-medium transition-colors"
          >
            + Add Repository
          </Link>
        )}
      </div>
      
      {selectedRepos.length > 1 && !isAddingRepo && (
        <div className="flex overflow-x-auto space-x-2 mb-6 pb-2">
          {selectedRepos.map(repo => (
            <Link 
              key={repo.id}
              href={`?repo_id=${repo.id}`}
              className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
                activeRepo?.id === repo.id 
                  ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 shadow-sm' 
                  : 'bg-white text-zinc-600 border border-zinc-200 hover:bg-zinc-50 dark:bg-zinc-800 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-700'
              }`}
            >
              {repo.name}
            </Link>
          ))}
        </div>
      )}

      <div className={`bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-zinc-200 dark:border-zinc-800 ${activeRepo && !isAddingRepo ? 'p-0 border-none shadow-none bg-transparent dark:bg-transparent' : 'p-10 md:p-16 text-center flex flex-col items-center justify-center min-h-[400px]'}`}>
        {isAddingRepo || (!activeRepo && hasGithub) ? (
          <div className="w-full">
            {isAddingRepo && selectedRepos.length > 0 && (
              <div className="flex justify-start mb-6">
                <Link href="/dashboard" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white flex items-center">
                  ← Back to Dashboard
                </Link>
              </div>
            )}
            <RepositorySelector />
          </div>
        ) : activeRepo ? (
          <RepositoryDashboard repo={activeRepo} />
        ) : (
          <>
            <div className="w-16 h-16 bg-zinc-100 dark:bg-zinc-800 rounded-full flex items-center justify-center mb-5">
              <svg className="w-8 h-8 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.092 2.027-.269 3.012M15.15 15.15l-.09.054a13.916 13.916 0 01-5.114 2.753M12 11c0-3.517 1.009-6.799 2.753-9.571m3.44 2.04l-.054.09A13.916 13.916 0 0016 11a4 4 0 11-8 0c0-1.017.092-2.027.269-3.012" />
              </svg>
            </div>
            
            <h3 className="text-xl font-semibold text-zinc-900 dark:text-white mb-3">
              Connect GitHub to get started
            </h3>
            
            <p className="text-zinc-500 dark:text-zinc-400 max-w-md mx-auto mb-8 leading-relaxed">
              TeslaLab AI needs access to your GitHub account to list your repositories, perform automated scans, and generate maintenance fixes.
            </p>

            {params.connect_error ? (
              <p className="mb-4 text-sm text-red-600 dark:text-red-400" role="alert">
                GitHub connection could not be started. Try again.
              </p>
            ) : null}

            <ConnectGitHubButton
              label="Connect GitHub App"
              className="inline-flex items-center justify-center py-2.5 px-5 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            />
          </>
        )}
      </div>
    </div>
  )
}
