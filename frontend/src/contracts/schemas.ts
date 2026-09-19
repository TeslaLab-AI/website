/**
 * Purpose:
 * Frozen Day 1 Data Contracts for TeslaLab AI Stage 0 (TypeScript Interfaces).
 * Shared across frontend, Engineer 2 (Planning), and Engineer 3 (Verification).
 */

export type FindingCategory = 'bugs' | 'dependencies' | 'security' | 'testing'
export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low'
export type TaskStatus = 'open' | 'in_progress' | 'resolved' | 'closed'

export type SessionState =
  | 'CREATED'
  | 'TRIAGED'
  | 'INVESTIGATING'
  | 'REPRODUCING'
  | 'ROOT_CAUSE'
  | 'PLANNING'
  | 'EXECUTING'
  | 'TESTING'
  | 'REPAIRING'
  | 'PR_READY'
  | 'HUMAN_REVIEW'
  | 'MERGED'
  | 'NEEDS_HUMAN'

export interface Finding {
  id: string
  category: FindingCategory
  severity: FindingSeverity
  title: string
  description: string
  file_path?: string | null
  line_number?: number | null
  metadata?: Record<string, any>
}

export interface Task {
  id: string
  workspace_id: string
  finding_id: string
  title: string
  category: FindingCategory
  severity: FindingSeverity
  status: TaskStatus
  created_at: string
  updated_at: string
}

export interface Session {
  id: string
  task_id: string
  workspace_id: string
  current_state: SessionState
  created_at: string
  updated_at: string
}

export interface ToolCall {
  step_index: number
  tool_name: string
  arguments: Record<string, any>
  expected_output?: string | null
}

export interface PlanSkeleton {
  id: string
  session_id: string
  task_id: string
  version: number
  status: string
  steps: ToolCall[]
  created_at: string
  updated_at: string
}

export type AgentEventType =
  | 'SESSION_STARTED'
  | 'SEARCHING_REPOSITORY'
  | 'READING_FILE'
  | 'HYPOTHESIS_GENERATED'
  | 'PLAN_CREATED'
  | 'CODE_MODIFIED'
  | 'TESTS_RUNNING'
  | 'PR_OPENED'
  | 'state_transition'

export interface AgentEvent {
  id: string
  session_id: string
  from_state?: SessionState | string
  to_state?: SessionState | string
  event_type: AgentEventType | string
  payload: Record<string, any>
  timestamp: string
}

