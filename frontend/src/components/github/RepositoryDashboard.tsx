/**
 * Purpose:
 * Renders the interactive repository dashboard for triggering scans and viewing results.
 *
 * Responsibilities:
 * - Display the currently selected repository.
 * - Trigger backend scans and poll the API for updates while a scan is in progress.
 * - Provide a tabbed interface (Overview, Bugs, Dependencies, Security, Testing).
 * - Render detailed findings with severity color-coding.
 */

'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/utils/supabase/client'
import { ScanProgressHUD } from './ScanProgressHUD'
import { ChatInterface } from './ChatInterface'
import { SessionStepper } from './SessionStepper'

interface Repo {
  id: string
  name: string
  owner: string
  default_branch: string
}

interface Scan {
  id: string
  status: 'in_progress' | 'completed' | 'failed'
  started_at: string
  completed_at: string | null
}

interface Finding {
  id: string
  category: 'bugs' | 'dependencies' | 'security' | 'testing'
  severity: 'critical' | 'high' | 'medium' | 'low'
  title: string
  description: string
  file_path: string
  line_number: number
}

type TabType = 'overview' | 'chat' | 'bugs' | 'dependencies' | 'security' | 'testing'

export function RepositoryDashboard({ repo }: { repo: Repo }) {
  const [activeTab, setActiveTab] = useState<TabType>('overview')
  const [scan, setScan] = useState<Scan | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [loading, setLoading] = useState(true)
  const [isScanning, setIsScanning] = useState(false)
  const [isRemoving, setIsRemoving] = useState(false)
  const [fixingId, setFixingId] = useState<string | null>(null)
  const [fixResults, setFixResults] = useState<Record<string, { pr_url: string, explanation: string } | { error: string }>>({})
  const [error, setError] = useState<string | null>(null)
  // Agentic fix state: keyed by finding ID
  const [agenticRuns, setAgenticRuns] = useState<Record<string, {
    runId: string
    status: 'running' | 'completed' | 'failed'
    phase: string
    logs: {timestamp: string, message: string}[]
    result: any
    error: string | null
  }>>({})
  // Day 1 Investigation & Session Machine state
  const [activeSessions, setActiveSessions] = useState<Record<string, { sessionId: string; taskId: string; state: string }>>({})
  const [investigatingId, setInvestigatingId] = useState<string | null>(null)
  const supabase = createClient()

  const loadSeededFindings = async () => {
    try {
      const res = await fetch('/api/findings/seeded')
      if (res.ok) {
        const data = await res.json()
        setFindings(data)
      }
    } catch (err) {
      console.error("Failed to load seeded findings", err)
    }
  }

  const handleInvestigate = async (findingId: string) => {
    if (investigatingId === findingId) return // Double-click guard
    setInvestigatingId(findingId)
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (session?.access_token) {
        headers['Authorization'] = `Bearer ${session.access_token}`
      }

      const res = await fetch(`/api/findings/${findingId}/investigate`, {
        method: 'POST',
        headers,
      })

      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to initialize investigation')
      }

      setActiveSessions(prev => ({
        ...prev,
        [findingId]: {
          sessionId: data.session_id,
          taskId: data.task_id,
          state: data.status || 'INVESTIGATING',
        },
      }))
    } catch (err: any) {
      alert(err.message || 'Investigation failed to initialize')
    } finally {
      setInvestigatingId(null)
    }
  }

  const handleRemoveRepo = async () => {
    const confirmed = window.confirm(
      `Are you sure you want to remove "${repo.name}"? This will delete all scan history and findings for this repository.`
    )
    if (!confirmed) return

    try {
      setIsRemoving(true)
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token) {
        throw new Error("Authentication required")
      }

      const res = await fetch(`/api/github/repositories/${repo.id}`, {
        method: 'DELETE',
        headers: {
          Authorization: `Bearer ${session.access_token}`
        }
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || "Failed to remove repository")
      }

      window.location.href = '/dashboard'
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "An error occurred while removing repository")
      setIsRemoving(false)
    }
  }

  const fetchLatestScan = async () => {
    try {
      // 1. Get the authenticated session token to pass to the backend
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) return

      // 2. Fetch the most recent scan for this specific repository
      const res = await fetch(`/api/github/scan/${repo.id}/latest`, {
        headers: { Authorization: `Bearer ${session.access_token}` }
      })
      if (res.ok) {
        const data = await res.json()

        // 3. Update the UI state with the fetched scan and its findings
        setScan(data.scan)
        setFindings(data.findings || [])

        // 4. If the scan is still running, ensure the scanning animation stays active
        if (data.scan?.status === 'in_progress') {
          setIsScanning(true)
        } else {
          setIsScanning(false)
        }
      }
    } catch (err) {
      console.error("Failed to fetch scan", err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Initial fetch when the component mounts
    fetchLatestScan()

    // Notice: We removed the Dashboard-level polling interval here.
    // The high-end ScanProgressHUD component handles its own real-time polling 
    // at a much faster rate (500ms) to ensure smooth animations.
  }, [repo.id])

  const startScan = async () => {
    try {
      // 1. Reset error states and trigger the scanning UI immediately
      setError(null)
      setIsScanning(true)
      setActiveTab('overview')

      const { data: { session } } = await supabase.auth.getSession()
      if (!session) throw new Error("Not authenticated")

      // 2. Call the backend to trigger the background scanning task
      const res = await fetch(`/api/github/scan/start`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ repository_id: repo.id })
      })

      if (!res.ok) {
        throw new Error("Failed to start scan")
      }

      // 3. Kick off a manual fetch immediately to update the UI with the 'in_progress' scan record
      fetchLatestScan()
    } catch (err: any) {
      setError(err.message)
      setIsScanning(false)
    }
  }

  const handleAgenticFix = async (findingId: string) => {
    try {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) throw new Error('Not authenticated')

      // Start the pipeline
      const res = await fetch('/api/github/fix/agentic', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${session.access_token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ repository_id: repo.id, finding_id: findingId })
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to start agentic fix')
      }
      const { run_id } = await res.json()

      // Initialize state
      setAgenticRuns(prev => ({ ...prev, [findingId]: { runId: run_id, status: 'running', phase: 'initializing', logs: [], result: null, error: null } }))

      // Poll for progress
      const poll = async () => {
        const pollRes = await fetch(`/api/github/fix/agentic/${run_id}`, {
          headers: { 'Authorization': `Bearer ${session.access_token}` }
        })
        if (!pollRes.ok) return
        const state = await pollRes.json()
        setAgenticRuns(prev => ({
          ...prev,
          [findingId]: {
            runId: run_id,
            status: state.status,
            phase: state.phase,
            logs: state.logs || [],
            result: state.result,
            error: state.error
          }
        }))
        if (state.status === 'running') {
          setTimeout(poll, 2000)  // poll every 2s while running
        }
      }
      setTimeout(poll, 1000)
    } catch (err: any) {
      setAgenticRuns(prev => ({ ...prev, [findingId]: { runId: '', status: 'failed', phase: 'failed', logs: [], result: null, error: err.message } }))
    }
  }

  const handleGenerateFix = async (findingId: string) => {
    try {
      setFixingId(findingId)
      setError(null)

      const { data: { session } } = await supabase.auth.getSession()
      if (!session) throw new Error("Not authenticated")

      const res = await fetch('/api/github/fix', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          repository_id: repo.id,
          finding_id: findingId
        })
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || "Failed to generate fix")
      }

      const data = await res.json()
      setFixResults(prev => ({
        ...prev,
        [findingId]: data
      }))
    } catch (err: any) {
      setFixResults(prev => ({
        ...prev,
        [findingId]: { error: err.message }
      }))
    } finally {
      setFixingId(null)
    }
  }

  const renderFindings = (category: string) => {
    const categoryFindings = findings.filter(f => f.category === category)

    if (loading || isScanning) {
      return (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-zinc-900 dark:border-white"></div>
        </div>
      )
    }

    if (categoryFindings.length === 0) {
      return (
        <div className="text-center py-10 space-y-3">
          <p className="text-zinc-500">No {category} found in current scan.</p>
          <button
            onClick={loadSeededFindings}
            className="px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-medium shadow-sm transition"
          >
            Load 6 Day 1 Evaluation Fixtures (3 Bugs, 2 Deps, 1 Security) ⚡
          </button>
        </div>
      )
    }

    return (
      <div className="space-y-4">
        <div className="p-3 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl flex items-center justify-between">
          <div>
            <h6 className="text-xs font-semibold text-zinc-900 dark:text-zinc-100 uppercase tracking-wide">
              Day 1 Evaluation Fixtures
            </h6>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
              Trigger [Investigate] to test idempotent Task creation and the 13-state Session Stepper.
            </p>
          </div>
          <button
            onClick={loadSeededFindings}
            className="text-xs px-2.5 py-1 bg-zinc-900 hover:bg-zinc-800 text-white dark:bg-zinc-100 dark:hover:bg-white dark:text-zinc-900 font-medium rounded-md shadow-sm transition"
          >
            Reset 6 Fixtures
          </button>
        </div>
        {categoryFindings.map(finding => (
          <div key={finding.id} className="p-4 bg-white dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700/50 rounded-xl shadow-sm text-left">
            <div className="flex justify-between items-start mb-2">
              <h5 className="font-semibold text-zinc-900 dark:text-zinc-100">{finding.title}</h5>
              <span className={`text-xs px-2 py-1 rounded-full font-medium ${finding.severity === 'critical' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' :
                  finding.severity === 'high' ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400' :
                    finding.severity === 'medium' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' :
                      'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                }`}>
                {finding.severity.toUpperCase()}
              </span>
            </div>
            <p className="text-sm text-zinc-600 dark:text-zinc-300 mb-3">{finding.description}</p>
            <div className="flex items-center space-x-2 text-xs font-mono text-zinc-500 bg-zinc-50 dark:bg-zinc-900 px-3 py-2 rounded-lg">
              <span>{finding.file_path}</span>
              {finding.line_number && (
                <>
                  <span className="text-zinc-300 dark:text-zinc-700">:</span>
                  <span className="text-blue-600 dark:text-blue-400">L{finding.line_number}</span>
                </>
              )}
            </div>

            {/* AI Fix Section */}
            <div className="mt-4 pt-4 border-t border-zinc-200 dark:border-zinc-700/50">
              {fixResults[finding.id] && 'pr_url' in fixResults[finding.id] ? (
                <div className="bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/30 rounded-lg p-3">
                  <div className="flex items-center space-x-2 text-emerald-700 dark:text-emerald-400 font-medium mb-2">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    <span>PR Opened ✅</span>
                  </div>
                  <p className="text-sm text-emerald-800 dark:text-emerald-300 mb-3 whitespace-pre-wrap">
                    {(fixResults[finding.id] as {pr_url: string, explanation: string}).explanation}
                  </p>
                  <a
                    href={(fixResults[finding.id] as {pr_url: string, explanation: string}).pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center space-x-1 text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <span>View Pull Request on GitHub</span>
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                </div>
              ) : fixResults[finding.id] && 'error' in fixResults[finding.id] ? (
                <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/30 rounded-lg p-3">
                  <p className="text-sm text-red-700 dark:text-red-400 mb-2">{(fixResults[finding.id] as {error: string}).error}</p>
                  <button
                    onClick={() => {
                      setFixResults(prev => { const n = {...prev}; delete n[finding.id]; return n })
                    }}
                    className="text-xs text-red-600 underline"
                  >Retry</button>
                </div>
              ) : agenticRuns[finding.id] ? (
                /* Agentic Fix Progress Panel */
                <div className="rounded-lg border border-zinc-200 dark:border-zinc-700 overflow-hidden">
                  <div className="px-3 py-2 bg-zinc-50 dark:bg-zinc-800/60 flex items-center justify-between">
                    <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300 uppercase tracking-wide">
                      🤖 Agentic Fix Pipeline
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      agenticRuns[finding.id].status === 'completed' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' :
                      agenticRuns[finding.id].status === 'failed' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' :
                      'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                    }`}>
                      {agenticRuns[finding.id].status === 'running' ? `⚙ ${agenticRuns[finding.id].phase}` :
                       agenticRuns[finding.id].status === 'completed' ? '✅ Done' : '❌ Failed'}
                    </span>
                  </div>
                  {/* Phase steps */}
                  <div className="px-3 py-2 space-y-1 max-h-32 overflow-y-auto text-xs font-mono text-zinc-500 dark:text-zinc-400 bg-zinc-950/5 dark:bg-zinc-900/40">
                    {agenticRuns[finding.id].logs.slice(-8).map((log, i) => (
                      <div key={i} className="leading-relaxed">{log.message}</div>
                    ))}
                    {agenticRuns[finding.id].status === 'running' && (
                      <div className="flex items-center space-x-1 text-blue-500">
                        <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                        <span>Processing...</span>
                      </div>
                    )}
                  </div>
                  {/* Result */}
                  {agenticRuns[finding.id].status === 'completed' && agenticRuns[finding.id].result && (
                    <div className="px-3 py-2 bg-emerald-50 dark:bg-emerald-900/10 border-t border-emerald-200 dark:border-emerald-800/30">
                      <p className="text-xs text-emerald-700 dark:text-emerald-400 mb-1">
                        Tests: {agenticRuns[finding.id].result.test_result} · Verify: {agenticRuns[finding.id].result.verify_result} · Attempts: {agenticRuns[finding.id].result.attempts}
                      </p>
                      <a href={agenticRuns[finding.id].result.pr_url} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center space-x-1 text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-700 px-2 py-1 rounded transition-colors">
                        <span>View PR on GitHub →</span>
                      </a>
                    </div>
                  )}
                  {agenticRuns[finding.id].status === 'failed' && (
                    <div className="px-3 py-2 bg-red-50 dark:bg-red-900/10 border-t border-red-200 dark:border-red-800/30">
                      <p className="text-xs text-red-600 dark:text-red-400">{agenticRuns[finding.id].error}</p>
                      <button onClick={() => setAgenticRuns(prev => { const n={...prev}; delete n[finding.id]; return n })}
                        className="text-xs text-red-500 underline mt-1">Retry</button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => handleInvestigate(finding.id)}
                    disabled={investigatingId === finding.id}
                    className="flex items-center space-x-1.5 text-sm font-medium px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-all shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Idempotently creates a Task and starts 13-state Agent Session"
                  >
                    {investigatingId === finding.id ? (
                      <><div className="animate-spin h-3.5 w-3.5 border-2 border-white/20 border-t-white rounded-full" /><span>Investigating...</span></>
                    ) : (
                      <><span>🔍</span><span>Investigate</span></>
                    )}
                  </button>
                  <button
                    onClick={() => handleGenerateFix(finding.id)}
                    disabled={fixingId === finding.id}
                    className="flex items-center space-x-2 text-sm font-medium px-3 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-lg transition-all shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {fixingId === finding.id ? (
                      <><div className="animate-spin h-4 w-4 border-2 border-white/20 border-t-white rounded-full" /><span>Fixing...</span></>
                    ) : (
                      <><span>✨</span><span>Quick Fix</span></>
                    )}
                  </button>
                  <button
                    onClick={() => handleAgenticFix(finding.id)}
                    className="flex items-center space-x-2 text-sm font-medium px-3 py-2 bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-700 hover:to-fuchsia-700 text-white rounded-lg transition-all shadow-sm"
                  >
                    <span>🤖</span><span>Agentic Fix</span>
                  </button>
                </div>
              )}
            </div>

            {/* Live Session Stepper HUD */}
            {activeSessions[finding.id] && (
              <div className="mt-4 pt-3 border-t border-zinc-100 dark:border-zinc-800/80">
                <SessionStepper
                  sessionId={activeSessions[finding.id].sessionId}
                  initialState={activeSessions[finding.id].state as any}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  const renderContent = () => {
    if (activeTab === 'overview') {
      return (
        <div className="space-y-6 flex-1 text-left">
          <div className="flex items-center justify-between py-4 border-b border-zinc-200 dark:border-zinc-700/50">
            <span className="text-zinc-500 dark:text-zinc-400">Last Scan</span>
            <span className="font-medium text-zinc-900 dark:text-zinc-300">
              {scan ? new Date(scan.started_at).toLocaleString() : 'Never'}
            </span>
          </div>

          <div className="flex items-center justify-between py-4 border-b border-zinc-200 dark:border-zinc-700/50">
            <span className="text-zinc-500 dark:text-zinc-400">Repository</span>
            <span className="font-medium text-zinc-900 dark:text-zinc-300">{repo.name}</span>
          </div>

          <div className="flex items-center justify-between py-4 border-b border-zinc-200 dark:border-zinc-700/50">
            <span className="text-zinc-500 dark:text-zinc-400">Branch</span>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700">
              {repo.default_branch}
            </span>
          </div>

          <div className="flex items-center justify-between py-4 border-b border-zinc-200 dark:border-zinc-700/50">
            <span className="text-zinc-500 dark:text-zinc-400">Status</span>
            <span className={`font-medium ${isScanning ? 'text-blue-500 animate-pulse' :
                scan?.status === 'failed' ? 'text-red-500' :
                  scan?.status === 'completed' ? 'text-emerald-500' : 'text-zinc-500'
              }`}>
              {isScanning ? 'Scanning...' : scan ? scan.status : 'Ready'}
            </span>
          </div>

          <div className="flex items-center justify-between py-4 border-b border-zinc-200 dark:border-zinc-700/50">
            <div>
              <span className="text-zinc-700 dark:text-zinc-300 font-medium block">Remove Repository</span>
              <span className="text-xs text-zinc-500 dark:text-zinc-400">Disconnect this repository and delete all its scan data</span>
            </div>
            <button
              onClick={handleRemoveRepo}
              disabled={isRemoving || isScanning}
              className="px-3 py-1.5 text-xs font-semibold text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100 dark:bg-red-950/40 dark:text-red-400 dark:hover:bg-red-900/50 border border-red-200 dark:border-red-900/50 rounded-lg transition-colors disabled:opacity-50"
            >
              {isRemoving ? 'Removing...' : 'Remove Repository'}
            </button>
          </div>

          {error && (
            <div className="text-red-500 text-sm mt-4 p-3 bg-red-50 dark:bg-red-900/10 rounded-lg">
              {error}
            </div>
          )}
        </div>
      )
    }

    return (
      <div className="h-full flex flex-col text-left">
        <h4 className="text-xl font-semibold text-zinc-900 dark:text-white mb-6 capitalize">{activeTab} Findings</h4>
        <div className="flex-1 overflow-y-auto pr-2">
          {renderFindings(activeTab)}
        </div>
      </div>
    )
  }

  const tabStyle = (tab: TabType, colorClass: string, activeClass: string) => {
    const isActive = activeTab === tab
    return `flex items-center space-x-3 w-full p-4 rounded-xl font-medium transition-all text-left border ${isActive
        ? `${activeClass} shadow-sm`
        : `bg-zinc-50 dark:bg-zinc-800/20 text-zinc-600 dark:text-zinc-400 border-transparent hover:bg-zinc-100 dark:hover:bg-zinc-800/40`
      }`
  }

  return (
    <div className="w-full max-w-5xl mx-auto text-left flex flex-col h-full min-h-[500px]">
      {/* Header Area */}
      <div className="flex items-center justify-between mb-8 pb-6 border-b border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center space-x-4 cursor-pointer" onClick={() => setActiveTab('overview')}>
          <div className="p-3 bg-blue-50 dark:bg-blue-500/10 rounded-xl">
            <svg className="w-8 h-8 text-blue-600 dark:text-blue-400" fill="currentColor" viewBox="0 0 24 24">
              <path fillRule="evenodd" d="M3 3a2 2 0 012-2h9.982a2 2 0 011.414.586l4.018 4.018A2 2 0 0121 7.018V21a2 2 0 01-2 2H5a2 2 0 01-2-2V3zm2-.5a.5.5 0 00-.5.5v18a.5.5 0 00.5.5h14a.5.5 0 00.5-.5V7.5h-4a1 1 0 01-1-1V1.5H5z" clipRule="evenodd" />
            </svg>
          </div>
          <div>
            <h3 className="text-2xl font-bold text-zinc-900 dark:text-white tracking-tight hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
              {repo.name}
            </h3>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
              {repo.owner}/{repo.name}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={handleRemoveRepo}
            disabled={isRemoving || isScanning}
            className="flex items-center space-x-1.5 px-3.5 py-2 text-sm font-medium text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100 dark:bg-red-950/30 dark:text-red-400 dark:hover:bg-red-900/40 border border-red-200 dark:border-red-900/40 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Remove repository from workspace"
          >
            {isRemoving ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-600 dark:border-red-400"></div>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            )}
            <span>{isRemoving ? 'Removing...' : 'Remove'}</span>
          </button>

          <button
            onClick={startScan}
            disabled={isScanning || isRemoving}
            className="flex items-center space-x-2 px-6 py-2.5 bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 text-sm font-semibold rounded-lg shadow-sm transition-all transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none"
          >
            {isScanning ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white dark:border-zinc-900"></div>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            <span>{isScanning ? 'SCANNING...' : 'SCAN'}</span>
          </button>
        </div>
      </div>

      {/* Dashboard Content */}
      {isScanning && scan?.id ? (
        <div className="flex-1 w-full animate-in fade-in zoom-in duration-500 fill-mode-both">
          <ScanProgressHUD
            scanId={scan.id}
            onComplete={() => {
              setIsScanning(false)
              fetchLatestScan()
            }}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 flex-1">
          {/* Left Column: Navigation Buttons */}
          <div className="md:col-span-4 flex flex-col space-y-3">
            <button
              onClick={() => setActiveTab('overview')}
              className={tabStyle('overview', '', 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-100 dark:border-blue-500/20')}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>
              <span>Overview</span>
            </button>

            <button
              onClick={() => setActiveTab('chat')}
              className={tabStyle('chat', '', 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 border-indigo-100 dark:border-indigo-500/20')}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" /></svg>
              <span>AI Assistant</span>
            </button>

            <div className="h-px bg-zinc-200 dark:bg-zinc-800 my-2"></div>

            <button
              onClick={() => setActiveTab('bugs')}
              className={tabStyle('bugs', '', 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 border-red-100 dark:border-red-500/20')}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
              <span>Bugs</span>
              {!loading && findings.some(f => f.category === 'bugs') && (
                <span className="ml-auto bg-red-100 text-red-600 dark:bg-red-900/30 text-xs py-0.5 px-2 rounded-full">
                  {findings.filter(f => f.category === 'bugs').length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('dependencies')}
              className={tabStyle('dependencies', '', 'bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-400 border-orange-100 dark:border-orange-500/20')}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" /></svg>
              <span>Dependencies</span>
              {!loading && findings.some(f => f.category === 'dependencies') && (
                <span className="ml-auto bg-orange-100 text-orange-600 dark:bg-orange-900/30 text-xs py-0.5 px-2 rounded-full">
                  {findings.filter(f => f.category === 'dependencies').length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('security')}
              className={tabStyle('security', '', 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-100 dark:border-emerald-500/20')}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
              <span>Security</span>
              {!loading && findings.some(f => f.category === 'security') && (
                <span className="ml-auto bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 text-xs py-0.5 px-2 rounded-full">
                  {findings.filter(f => f.category === 'security').length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('testing')}
              className={tabStyle('testing', '', 'bg-purple-50 dark:bg-purple-500/10 text-purple-700 dark:text-purple-400 border-purple-100 dark:border-purple-500/20')}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" /></svg>
              <span>Testing</span>
              {!loading && findings.some(f => f.category === 'testing') && (
                <span className="ml-auto bg-purple-100 text-purple-600 dark:bg-purple-900/30 text-xs py-0.5 px-2 rounded-full">
                  {findings.filter(f => f.category === 'testing').length}
                </span>
              )}
            </button>
          </div>

          {/* Right Column: Dynamic Content */}
          <div className="md:col-span-8 bg-zinc-50 dark:bg-zinc-800/30 border border-zinc-200 dark:border-zinc-700/50 rounded-2xl p-8">
            {activeTab === 'overview' ? (
              <>
                <h4 className="text-xl font-semibold text-zinc-900 dark:text-white mb-6">Repository Overview</h4>
                {renderContent()}
              </>
            ) : activeTab === 'chat' ? (
              <ChatInterface repoId={repo.id} />
            ) : (
              renderContent()
            )}
          </div>
        </div>
      )}
    </div>
  )
}
