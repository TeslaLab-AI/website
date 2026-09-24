'use client'

import React, { useState, useEffect } from 'react'
import { SessionState } from '@/contracts/schemas'
import { ActivityStream } from './ActivityStream'

interface SessionStepperProps {
  sessionId: string
  initialState?: SessionState
  onTransition?: (newState: SessionState) => void
}

interface EventLog {
  id: string
  from_state: string
  to_state: string
  event_type: string
  timestamp: string
  payload?: any
}

// 7-phase visible stepper mapping to the 13-state engine
const DISPLAY_STEPS = [
  { id: 'investigating', label: 'Investigating', states: ['CREATED', 'TRIAGED', 'INVESTIGATING'] },
  { id: 'root_cause', label: 'Root Cause', states: ['ROOT_CAUSE'] },
  { id: 'reproducing', label: 'Reproducing', states: ['REPRODUCING'] },
  { id: 'plan', label: 'Plan', states: ['PLANNING'] },
  { id: 'fix', label: 'Fix', states: ['EXECUTING', 'REPAIRING'] },
  { id: 'tests', label: 'Tests', states: ['TESTING'] },
  { id: 'pr', label: 'PR', states: ['PR_READY', 'HUMAN_REVIEW', 'MERGED'] },
]

export function SessionStepper({ sessionId, initialState = 'INVESTIGATING', onTransition }: SessionStepperProps) {
  const [currentState, setCurrentState] = useState<SessionState>(initialState)
  const [events, setEvents] = useState<EventLog[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'stepper' | 'stream' | 'logs'>('stepper')


  // Poll session state from backend every 2.5 seconds
  useEffect(() => {
    let isMounted = true
    let interval: NodeJS.Timeout

    const fetchSession = async () => {
      try {
        const res = await fetch(`/api/sessions/${sessionId}`)
        if (!res.ok) return
        const data = await res.json()
        if (isMounted && data?.session?.current_state) {
          const newState = data.session.current_state
          setCurrentState(newState)
          if (data.events) {
            setEvents(data.events)
          }
          // Stop polling if we reach a terminal state
          if (['FAILED', 'NEEDS_HUMAN', 'MERGED', 'CANCELLED'].includes(newState)) {
            clearInterval(interval)
          }
        }
      } catch (err) {
        // silent catch on polling
      }
    }

    fetchSession()
    interval = setInterval(fetchSession, 2500)
    return () => {
      isMounted = false
      clearInterval(interval)
    }
  }, [sessionId])

  // Determine which visual step index is active
  const activeStepIndex = DISPLAY_STEPS.findIndex(step => step.states.includes(currentState))
  const isTerminalNeedsHuman = currentState === 'NEEDS_HUMAN'
  const isTerminalMerged = currentState === 'MERGED'

  // Manual transition trigger for testing/demoing progression in real-time
  const handleTransition = async (target: SessionState) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/sessions/${sessionId}/transition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_state: target }),
      })

      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.detail || 'Transition failed')
      }

      setCurrentState(target)
      onTransition?.(target)
      // Append immediate local event
      setEvents(prev => [
        ...prev,
        {
          id: Math.random().toString(),
          from_state: currentState,
          to_state: target,
          event_type: 'state_transition',
          timestamp: data.timestamp || new Date().toISOString(),
        },
      ])
    } catch (err: any) {
      setError(err.message || 'Illegal state transition')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
          </span>
          <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 uppercase tracking-wider">
            Live Session Engine
          </h4>
          <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700">
            {currentState}
          </span>
        </div>

        <div className="flex items-center space-x-2 text-xs">
          <button
            onClick={() => setActiveTab('stepper')}
            className={`px-2.5 py-1 rounded-md transition-colors ${
              activeTab === 'stepper'
                ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-medium'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >
            Stepper
          </button>
          <button
            onClick={() => setActiveTab('stream')}
            className={`px-2.5 py-1 rounded-md transition-colors flex items-center space-x-1.5 ${
              activeTab === 'stream'
                ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-medium'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>Live Stream</span>
          </button>
          <button
            onClick={() => setActiveTab('logs')}
            className={`px-2.5 py-1 rounded-md transition-colors ${
              activeTab === 'logs'
                ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-medium'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >
            Audit Log ({events.length})
          </button>
        </div>

      </div>

      {error && (
        <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 rounded-lg text-xs text-red-600 dark:text-red-400">
          ⚠️ {error}
        </div>
      )}

      {activeTab === 'stepper' ? (
        <div className="py-2">
          {/* 7-phase visual Stepper */}
          <div className="relative flex items-center justify-between">
            {DISPLAY_STEPS.map((step, idx) => {
              const isPast = activeStepIndex > idx
              const isCurrent = activeStepIndex === idx
              return (
                <div key={step.id} className="flex-1 flex flex-col items-center relative">
                  {/* Connecting line */}
                  {idx > 0 && (
                    <div
                      className={`absolute top-3 right-1/2 left-[-50%] h-0.5 -translate-y-1/2 z-0 transition-colors duration-300 ${
                        isPast ? 'bg-emerald-500' : 'bg-zinc-200 dark:bg-zinc-800'
                      }`}
                    />
                  )}

                  {/* Step Node */}
                  <div
                    className={`relative z-10 w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold transition-all duration-300 ${
                      isCurrent
                        ? 'bg-emerald-500 text-white ring-4 ring-emerald-500/20 shadow-md scale-110'
                        : isPast
                        ? 'bg-emerald-500 text-white'
                        : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-500 border border-zinc-200 dark:border-zinc-700'
                    }`}
                  >
                    {isPast ? '✓' : idx + 1}
                  </div>

                  <span
                    className={`mt-2 text-xs font-medium text-center transition-colors ${
                      isCurrent
                        ? 'text-emerald-600 dark:text-emerald-400 font-semibold'
                        : isPast
                        ? 'text-zinc-700 dark:text-zinc-300'
                        : 'text-zinc-400 dark:text-zinc-600'
                    }`}
                  >
                    {step.label}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Interactive State Progression Buttons for Evaluation & Testing */}
          <div className="mt-6 pt-4 border-t border-zinc-100 dark:border-zinc-800/80 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-zinc-500">Step Progression (E1 Test Bar):</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {currentState === 'INVESTIGATING' && (
                <button
                  disabled={loading}
                  onClick={() => handleTransition('ROOT_CAUSE')}
                  className="px-2.5 py-1 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded font-medium disabled:opacity-50 transition"
                >
                  Step to Root Cause →
                </button>
              )}
              {currentState === 'ROOT_CAUSE' && (
                <button
                  disabled={loading}
                  onClick={() => handleTransition('REPRODUCING')}
                  className="px-2.5 py-1 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded font-medium disabled:opacity-50 transition"
                >
                  Step to Reproducing →
                </button>
              )}
              {currentState === 'REPRODUCING' && (
                <button
                  disabled={loading}
                  onClick={() => handleTransition('PLANNING')}
                  className="px-2.5 py-1 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded font-medium disabled:opacity-50 transition"
                >
                  Step to Planning →
                </button>
              )}
              {currentState === 'PLANNING' && (
                <button
                  disabled={loading}
                  onClick={() => handleTransition('EXECUTING')}
                  className="px-2.5 py-1 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded font-medium disabled:opacity-50 transition"
                >
                  Step to Executing →
                </button>
              )}
              {currentState === 'EXECUTING' && (
                <button
                  disabled={loading}
                  onClick={() => handleTransition('TESTING')}
                  className="px-2.5 py-1 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded font-medium disabled:opacity-50 transition"
                >
                  Step to Testing →
                </button>
              )}
              {currentState === 'TESTING' && (
                <button
                  disabled={loading}
                  onClick={() => handleTransition('PR_READY')}
                  className="px-2.5 py-1 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded font-medium disabled:opacity-50 transition"
                >
                  Step to PR Ready →
                </button>
              )}

              {/* Invalid state test button to test AC-E1-D1-04 guard */}
              <button
                disabled={loading}
                onClick={() => handleTransition('MERGED')}
                className="px-2 py-1 text-xs text-zinc-400 hover:text-red-500 border border-zinc-200 dark:border-zinc-800 rounded transition"
                title="Tests illegal jump guard (raises 400)"
              >
                Test Illegal Jump ⚠️
              </button>
            </div>
          </div>

          {/* Real-time terminal activity stream preview */}
          <div className="mt-4 pt-3 border-t border-zinc-100 dark:border-zinc-800/80">
            <ActivityStream sessionId={sessionId} maxHeight="220px" />
          </div>
        </div>
      ) : activeTab === 'stream' ? (
        /* Dedicated Full-height Live Activity Stream Tab */
        <div className="py-2">
          <ActivityStream sessionId={sessionId} maxHeight="480px" />
        </div>
      ) : (
        /* Event audit logs with microsecond precision */
        <div className="max-h-48 overflow-y-auto space-y-1.5 font-mono text-xs text-zinc-600 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-950 p-3 rounded-lg border border-zinc-100 dark:border-zinc-800">
          {events.length === 0 ? (
            <p className="text-zinc-400 italic">No state transitions recorded yet.</p>
          ) : (
            events.map((evt, i) => (
              <div key={evt.id || i} className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-900 pb-1">
                <span>
                  <span className="text-emerald-500 font-medium">{evt.from_state}</span>
                  <span className="text-zinc-400 mx-1">→</span>
                  <span className="text-indigo-500 font-medium">{evt.to_state}</span>
                  <span className="text-zinc-400 ml-2 text-[10px]">({evt.event_type})</span>
                </span>
                <span className="text-[10px] text-zinc-400">{evt.timestamp}</span>
              </div>
            ))
          )}
        </div>
      )}

    </div>
  )
}
