/**
 * Purpose:
 * Renders the dashboard workspace home, including GitHub connection empty state.
 *
 * Responsibilities:
 * - Prompt the user to start GitHub App installation when no install exists.
 */
import { ConnectGitHubButton } from '@/components/github/ConnectGitHubButton'
import { RepositorySelector } from '@/components/github/RepositorySelector'
import { createClient } from '@/utils/supabase/server'

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ connect_error?: string }>
}) {
  const params = await searchParams

  const supabase = await createClient()
  const { data: workspaces } = await supabase.from('workspaces').select('*').limit(1)
  const workspace = workspaces?.[0]
  
  let hasGithub = false
  let selectedRepo = null
  
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
        .limit(1)
      selectedRepo = repos?.[0]
    }
  }

  return (
    <div className="p-6 md:p-10 w-full max-w-5xl mx-auto">
      <h2 className="text-2xl font-bold text-zinc-900 dark:text-white mb-8">
        Repository Scan
      </h2>
      


      <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-zinc-200 dark:border-zinc-800 p-10 md:p-16 text-center flex flex-col items-center justify-center min-h-[400px]">
        {selectedRepo ? (
          <div className="w-full max-w-2xl mx-auto text-left">
            <h3 className="text-xl font-semibold text-zinc-900 dark:text-white mb-4">Connected Repository</h3>
            <div className="p-6 bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700 rounded-xl">
              <div className="flex items-center space-x-3 mb-2">
                <svg className="w-6 h-6 text-zinc-700 dark:text-zinc-300" fill="currentColor" viewBox="0 0 24 24">
                  <path fillRule="evenodd" d="M3 3a2 2 0 012-2h9.982a2 2 0 011.414.586l4.018 4.018A2 2 0 0121 7.018V21a2 2 0 01-2 2H5a2 2 0 01-2-2V3zm2-.5a.5.5 0 00-.5.5v18a.5.5 0 00.5.5h14a.5.5 0 00.5-.5V7.5h-4a1 1 0 01-1-1V1.5H5z" clipRule="evenodd" />
                </svg>
                <h4 className="text-lg font-medium text-zinc-900 dark:text-white">
                  {selectedRepo.owner}/{selectedRepo.name}
                </h4>
              </div>
              <p className="text-sm text-zinc-500 dark:text-zinc-400">Default branch: {selectedRepo.default_branch}</p>
            </div>
          </div>
        ) : hasGithub ? (
          <RepositorySelector />
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
