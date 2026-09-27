'use client'

import React, { useState, useEffect, useRef } from 'react'
import { AgentEvent, AgentEventType } from '@/contracts/schemas'

interface ActivityStreamProps {
  sessionId: string
  initialEvents?: AgentEvent[]
  onNewEvent?: (event: AgentEvent) => void
  maxHeight?: string
}

// Styling configurations for each structured event type
const EVENT_BADGES: Record<
  string,
  { label: string; bg: string; text: string; border: string; dot: string }
> = {
  SESSION_STARTED: {
    label: 'SESSION STARTED',
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    border: 'border-emerald-500/30',
    dot: 'bg-emerald-400',
  },
  SEARCHING_REPOSITORY: {
    label: 'SEARCH REPO',
    bg: 'bg-sky-500/10',
    text: 'text-sky-400',
    border: 'border-sky-500/30',
    dot: 'bg-sky-400',
  },
  READING_FILE: {
    label: 'READ FILE',
    bg: 'bg-cyan-500/10',
    text: 'text-cyan-400',
    border: 'border-cyan-500/30',
    dot: 'bg-cyan-400',
  },
  HYPOTHESIS_GENERATED: {
    label: 'HYPOTHESIS',
    bg: 'bg-violet-500/10',
    text: 'text-violet-400',
    border: 'border-violet-500/30',
    dot: 'bg-violet-400',
  },
  PLAN_CREATED: {
    label: 'PLAN CREATED',
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
  },
  CODE_MODIFIED: {
    label: 'CODE MODIFIED',
    bg: 'bg-lime-500/10',
    text: 'text-lime-400',
    border: 'border-lime-500/30',
    dot: 'bg-lime-400',
  },
  TESTS_RUNNING: {
    label: 'TESTS RUNNING',
    bg: 'bg-yellow-500/10',
    text: 'text-yellow-400',
    border: 'border-yellow-500/30',
    dot: 'bg-yellow-400',
  },
  PR_OPENED: {
    label: 'PR OPENED',
    bg: 'bg-fuchsia-500/10',
    text: 'text-fuchsia-400',
    border: 'border-fuchsia-500/30',
    dot: 'bg-fuchsia-400',
  },
  state_transition: {
    label: 'STATE TRANSITION',
    bg: 'bg-indigo-500/10',
    text: 'text-indigo-400',
    border: 'border-indigo-500/30',
    dot: 'bg-indigo-400',
  },
}

export function ActivityStream({
  sessionId,
  initialEvents = [],
  onNewEvent,
  maxHeight = '320px',
}: ActivityStreamProps) {
  const [events, setEvents] = useState<AgentEvent[]>(initialEvents)
  const [connectionStatus, setConnectionStatus] = useState<
    'connecting' | 'connected' | 'reconnecting' | 'disconnected'
  >('connecting')
  const [connectionProtocol, setConnectionProtocol] = useState<'ws' | 'sse' | 'none'>('none')
  const [autoScroll, setAutoScroll] = useState<boolean>(true)
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState<string>('')

  const scrollAnchorRef = useRef<HTMLDivElement>(null)
  const terminalBodyRef = useRef<HTMLDivElement>(null)

  // Auto-scroll handler
  useEffect(() => {
    if (autoScroll && scrollAnchorRef.current) {
      scrollAnchorRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [events, autoScroll])

  // Real-time Event Streaming Connection (WebSocket with SSE fallback)
  useEffect(() => {
    let ws: WebSocket | null = null
    let eventSource: EventSource | null = null
    let isMounted = true

    const connectWebSocket = () => {
      setConnectionStatus('connecting')
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      // Use direct backend port 8000 if in local dev, or proxy rewrite
      const host = window.location.hostname === 'localhost' ? 'localhost:8000' : window.location.host
      const wsUrl = `${protocol}//${host}/sessions/${sessionId}/stream`

      try {
        ws = new WebSocket(wsUrl)

        ws.onopen = () => {
          if (!isMounted) return
          setConnectionStatus('connected')
          setConnectionProtocol('ws')
        }

        ws.onmessage = (event) => {
          if (!isMounted) return
          try {
            const data: AgentEvent = JSON.parse(event.data)
            setEvents((prev) => {
              if (prev.some((e) => e.id === data.id)) return prev
              return [...prev, data]
            })
            onNewEvent?.(data)
          } catch (err) {
            console.error('Failed to parse WebSocket event:', err)
          }
        }

        ws.onerror = () => {
          // Fallback to SSE if WebSocket encounters error
          if (ws) {
            ws.close()
          }
        }

        ws.onclose = () => {
          if (!isMounted) return
          // Fallback to SSE
          connectSSE()
        }
      } catch (err) {
        connectSSE()
      }
    }

    const connectSSE = () => {
      if (!isMounted) return
      setConnectionStatus('connecting')
      const sseUrl = `/api/sessions/${sessionId}/stream`

      try {
        eventSource = new EventSource(sseUrl)

        eventSource.onopen = () => {
          if (!isMounted) return
          setConnectionStatus('connected')
          setConnectionProtocol('sse')
        }

        eventSource.onmessage = (event) => {
          if (!isMounted) return
          try {
            const data: AgentEvent = JSON.parse(event.data)
            setEvents((prev) => {
              if (prev.some((e) => e.id === data.id)) return prev
              return [...prev, data]
            })
            onNewEvent?.(data)
          } catch (err) {
            // Heartbeats (ping) or parse skips
          }
        }

        eventSource.onerror = () => {
          if (!isMounted) return
          setConnectionStatus('disconnected')
        }
      } catch (err) {
        setConnectionStatus('disconnected')
      }
    }

    connectWebSocket()

    return () => {
      isMounted = false
      if (ws) ws.close()
      if (eventSource) eventSource.close()
    }
  }, [sessionId, onNewEvent])

  const filteredEvents = events.filter((ev) => {
    if (!searchQuery) return true
    const q = searchQuery.toLowerCase()
    return (
      ev.event_type.toLowerCase().includes(q) ||
      JSON.stringify(ev.payload || {}).toLowerCase().includes(q)
    )
  })

  const formatTime = (ts: string) => {
    try {
      const d = new Date(ts)
      return d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
        '.' + String(d.getMilliseconds()).padStart(3, '0')
    } catch {
      return ts
    }
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 font-mono text-xs shadow-2xl overflow-hidden text-zinc-300">
      {/* Terminal Titlebar HUD */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900/90 border-b border-zinc-800 backdrop-blur">
        <div className="flex items-center space-x-3">
          <div className="flex space-x-1.5">
            <div className="h-2.5 w-2.5 rounded-full bg-red-500/80"></div>
            <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/80"></div>
            <div className="h-2.5 w-2.5 rounded-full bg-emerald-500/80"></div>
          </div>
          <span className="text-zinc-400 font-medium tracking-tight">
            agent-activity.log <span className="text-zinc-600">[{sessionId.slice(0, 8)}]</span>
          </span>
        </div>

        <div className="flex items-center space-x-3 text-[11px]">
          {/* Connection Status Pill */}
          <div className="flex items-center space-x-1.5 px-2 py-0.5 rounded-full bg-zinc-800/80 border border-zinc-700/60">
            <span className="relative flex h-2 w-2">
              {connectionStatus === 'connected' && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              )}
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  connectionStatus === 'connected'
                    ? 'bg-emerald-400'
                    : connectionStatus === 'connecting'
                    ? 'bg-yellow-400'
                    : 'bg-zinc-500'
                }`}
              ></span>
            </span>
            <span className="capitalize text-zinc-300 font-sans text-[10px]">
              {connectionStatus === 'connected' ? `${connectionProtocol.toUpperCase()} LIVE` : connectionStatus}
            </span>
          </div>

          {/* Auto-scroll lock toggle */}
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`px-2 py-0.5 rounded border transition-colors ${
              autoScroll
                ? 'bg-zinc-800 border-zinc-700 text-zinc-200'
                : 'bg-transparent border-zinc-800 text-zinc-500 hover:text-zinc-400'
            }`}
            title="Toggle automatic scrolling to newest events"
          >
            {autoScroll ? '⚡ Lock Scroll' : '⏸ Manual'}
          </button>

          {/* Search filter input */}
          <input
            type="text"
            placeholder="filter..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-20 sm:w-28 px-2 py-0.5 bg-zinc-950/70 border border-zinc-800 rounded text-zinc-300 placeholder-zinc-600 focus:outline-none focus:border-zinc-600"
          />
        </div>
      </div>

      {/* Terminal Body with auto-scroll */}
      <div
        ref={terminalBodyRef}
        style={{ maxHeight }}
        className="p-3 overflow-y-auto space-y-1.5 scrollbar-thin scrollbar-thumb-zinc-800"
      >
        {filteredEvents.length === 0 ? (
          <div className="py-8 text-center text-zinc-600 italic">
            Waiting for agent step events... [SESSION: {sessionId.slice(0, 8)}]
          </div>
        ) : (
          filteredEvents.map((ev, index) => {
            const badge = EVENT_BADGES[ev.event_type] || {
              label: ev.event_type,
              bg: 'bg-zinc-800/50',
              text: 'text-zinc-400',
              border: 'border-zinc-700/50',
              dot: 'bg-zinc-400',
            }
            const isExpanded = expandedEventId === ev.id
            const payloadSummary = ev.payload?.message || ev.payload?.query || ev.payload?.file || ev.payload?.hypothesis || ''

            return (
              <div
                key={ev.id || index}
                className="group rounded-md border border-transparent hover:border-zinc-800/80 hover:bg-zinc-900/40 p-1.5 transition-all"
              >
                <div
                  className="flex items-start justify-between cursor-pointer space-x-2"
                  onClick={() => setExpandedEventId(isExpanded ? null : ev.id)}
                >
                  <div className="flex items-center space-x-2.5 min-w-0">
                    <span className="text-zinc-600 select-none text-[10px] w-16 shrink-0">
                      {formatTime(ev.timestamp)}
                    </span>

                    {/* Status Pill Badge */}
                    <span
                      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border ${badge.bg} ${badge.text} ${badge.border} shrink-0`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${badge.dot} mr-1.5 animate-pulse`}></span>
                      {badge.label}
                    </span>

                    {/* Step summary message */}
                    <span className="text-zinc-300 truncate text-[11px]">
                      {payloadSummary ? (
                        <span className="text-zinc-300">{payloadSummary}</span>
                      ) : (
                        <span className="text-zinc-500 italic">
                          {ev.from_state && ev.to_state ? `${ev.from_state} → ${ev.to_state}` : 'Step completed'}
                        </span>
                      )}
                    </span>
                  </div>

                  <span className="text-zinc-600 group-hover:text-zinc-400 text-[10px] shrink-0 font-sans">
                    {isExpanded ? '▲ hide' : '▼ json'}
                  </span>
                </div>

                {/* Collapsible JSON payload inspector */}
                {isExpanded && (
                  <div className="mt-2 p-2.5 rounded bg-zinc-950/90 border border-zinc-800/90 overflow-x-auto text-[11px] text-zinc-400">
                    <pre className="text-emerald-400/90 font-mono">
                      {JSON.stringify(
                        {
                          event_id: ev.id,
                          event_type: ev.event_type,
                          from_state: ev.from_state,
                          to_state: ev.to_state,
                          timestamp: ev.timestamp,
                          payload: ev.payload,
                        },
                        null,
                        2
                      )}
                    </pre>
                  </div>
                )}
              </div>
            )
          })
        )}
        <div ref={scrollAnchorRef} />
      </div>
    </div>
  )
}
