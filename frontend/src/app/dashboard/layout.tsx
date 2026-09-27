/**
 * Purpose:
 * Renders the authenticated dashboard chrome (workspace, GitHub connect, user).
 *
 * Responsibilities:
 * - Load the current user and workspace for the sidebar.
 * - Start GitHub App installation through the shared Connect GitHub control.
 */
import { createClient } from '@/utils/supabase/server'
import { logoutUser } from '@/app/actions/auth'
import { ConnectGitHubButton } from '@/components/github/ConnectGitHubButton'
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const supabase = await createClient()
  
  // The route is already protected by middleware, but we fetch the user 
  // here server-side to display their profile information.
  const { data: { user } } = await supabase.auth.getUser()
  
  // Fallback to 'User' if metadata is missing
  const fullName = user?.user_metadata?.full_name || 'User'
  const initial = fullName.charAt(0).toUpperCase()

  // Fetch workspace explicitly handling cardinality
  const { data: workspaces } = await supabase
    .from('workspaces')
    .select('*')
    .limit(1)
    
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
    <div className="flex flex-col md:flex-row min-h-screen bg-zinc-50 dark:bg-black font-sans">
      

      <aside className="w-full md:w-64 bg-white dark:bg-zinc-900 border-b md:border-b-0 md:border-r border-zinc-200 dark:border-zinc-800 flex flex-col shrink-0">
        

        <div className="p-5 border-b border-zinc-200 dark:border-zinc-800">
          <h1 className="font-bold text-lg text-zinc-900 dark:text-white">
            {workspace ? workspace.name : 'No Workspace Found'}
          </h1>
        </div>
        

        <div className="flex-1 p-5 overflow-y-auto">

          {hasGithub ? (
            <div className="space-y-2">
              <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Repositories</h2>
              {selectedRepo ? (
                <div className="p-3 bg-white dark:bg-zinc-800 rounded-lg border border-zinc-200 dark:border-zinc-700 shadow-sm flex items-center space-x-3">
                  <svg className="w-5 h-5 text-zinc-500" fill="currentColor" viewBox="0 0 24 24">
                    <path fillRule="evenodd" d="M3 3a2 2 0 012-2h9.982a2 2 0 011.414.586l4.018 4.018A2 2 0 0121 7.018V21a2 2 0 01-2 2H5a2 2 0 01-2-2V3zm2-.5a.5.5 0 00-.5.5v18a.5.5 0 00.5.5h14a.5.5 0 00.5-.5V7.5h-4a1 1 0 01-1-1V1.5H5z" clipRule="evenodd" />
                  </svg>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-zinc-900 dark:text-white truncate">{selectedRepo.name}</p>
                    <p className="text-xs text-zinc-500 truncate">{selectedRepo.owner}</p>
                  </div>
                </div>
              ) : (
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg border border-dashed border-zinc-200 dark:border-zinc-700">
                  <p className="text-sm text-zinc-500 dark:text-zinc-400 italic text-center">
                    No repositories connected.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <ConnectGitHubButton
              label="Connect GitHub"
              disabled={!workspace}
              className="w-full flex items-center justify-center py-2 px-4 border border-zinc-300 dark:border-zinc-700 rounded-lg shadow-sm text-sm font-medium text-zinc-700 dark:text-zinc-300 bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-zinc-500 disabled:opacity-50 transition-colors mb-8"
            >
              <svg className="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
              </svg>
            </ConnectGitHubButton>
          )}

        </div>


        <div className="p-5 border-t border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3 overflow-hidden">
              <div className="w-9 h-9 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center flex-shrink-0">
                <span className="text-sm font-semibold text-blue-700 dark:text-blue-400">
                  {initial}
                </span>
              </div>
              <div className="flex-1 min-w-0 pr-2">
                <p className="text-sm font-medium text-zinc-900 dark:text-white truncate">
                  {fullName}
                </p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 truncate">
                  {user?.email}
                </p>
              </div>
            </div>
            <form action={logoutUser}>
              <button 
                type="submit"
                className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white transition-colors p-1"
                title="Log out"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            </form>
          </div>
        </div>
      </aside>


      <main className="flex-1 flex flex-col min-w-0 overflow-x-hidden">
        {children}
      </main>
      
    </div>
  )
}
