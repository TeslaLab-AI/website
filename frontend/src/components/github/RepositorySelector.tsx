/**
 * Purpose:
 * Renders the GitHub repository selector.
 *
 * Responsibilities:
 * - Fetch available repositories from the backend for the current installation.
 * - Allow the user to select one repository.
 * - Submit the selected repository to the backend.
 * - Refresh the page state upon successful selection.
 */

'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'

type Repository = {
  id: number
  owner: string
  name: string
  default_branch: string
  full_name: string
  private: boolean
}

export function RepositorySelector() {
  const router = useRouter()
  const [repos, setRepos] = useState<Repository[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selecting, setSelecting] = useState<number | null>(null)

  useEffect(() => {
    async function loadRepos() {
      try {
        const supabase = createClient()
        const { data: { session } } = await supabase.auth.getSession()
        
        if (!session?.access_token) {
          setError('Authentication required')
          setLoading(false)
          return
        }

        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000'
        const res = await fetch(`${backendUrl}/api/github/repositories/available`, {
          headers: {
            Authorization: `Bearer ${session.access_token}`
          }
        })
        
        if (!res.ok) {
          throw new Error('Failed to fetch repositories')
        }
        
        const data = await res.json()
        setRepos(data.repositories || [])
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Unknown error occurred')
      } finally {
        setLoading(false)
      }
    }
    
    loadRepos()
  }, [])

  const handleSelect = async (repo: Repository) => {
    setSelecting(repo.id)
    try {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000'
      const res = await fetch(`${backendUrl}/api/github/repositories/select`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session?.access_token}`
        },
        body: JSON.stringify({
          github_repo_id: repo.id,
          owner: repo.owner,
          name: repo.name,
          default_branch: repo.default_branch
        })
      })
      
      if (!res.ok) {
        throw new Error('Failed to select repository')
      }
      
      // Refresh Next.js server components to reflect the selection
      router.refresh()
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to select repository')
      setSelecting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-12 text-zinc-500">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-zinc-500"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center p-6 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg">
        {error}
      </div>
    )
  }

  if (repos.length === 0) {
    return (
      <div className="text-center p-6 bg-zinc-50 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 rounded-lg">
        No repositories found for this installation.
      </div>
    )
  }

  return (
    <div className="w-full max-w-2xl mx-auto space-y-4">
      <h3 className="text-lg font-medium text-zinc-900 dark:text-white mb-4">Select a Repository</h3>
      <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl divide-y divide-zinc-200 dark:divide-zinc-800 shadow-sm max-h-[500px] overflow-y-auto">
        {repos.map((repo) => (
          <div key={repo.id} className="flex items-center justify-between p-4 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors">
            <div className="flex items-center space-x-3">
              <svg className="w-5 h-5 text-zinc-400" fill="currentColor" viewBox="0 0 24 24">
                <path fillRule="evenodd" d="M3 3a2 2 0 012-2h9.982a2 2 0 011.414.586l4.018 4.018A2 2 0 0121 7.018V21a2 2 0 01-2 2H5a2 2 0 01-2-2V3zm2-.5a.5.5 0 00-.5.5v18a.5.5 0 00.5.5h14a.5.5 0 00.5-.5V7.5h-4a1 1 0 01-1-1V1.5H5z" clipRule="evenodd" />
              </svg>
              <div>
                <p className="text-sm font-medium text-zinc-900 dark:text-white">{repo.full_name}</p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">{repo.private ? 'Private' : 'Public'} • {repo.default_branch}</p>
              </div>
            </div>
            <button
              onClick={() => handleSelect(repo)}
              disabled={selecting !== null}
              className="px-3 py-1.5 text-xs font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50 rounded-md transition-colors disabled:opacity-50"
            >
              {selecting === repo.id ? 'Selecting...' : 'Select'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
