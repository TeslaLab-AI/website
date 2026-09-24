-- Migration 009 — Agent Foundation, Sessions, Events, Plans, and Executions

-- 1. Tasks Table: Maps a scanner finding into a trackable remediation task
CREATE TABLE IF NOT EXISTS public.tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    finding_id text NOT NULL,
    title text NOT NULL,
    category text NOT NULL,
    severity text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    UNIQUE(workspace_id, finding_id)
);

-- 2. Agent Sessions Table: Tracks the 13-state execution engine per task
CREATE TABLE IF NOT EXISTS public.agent_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    current_state text NOT NULL DEFAULT 'CREATED',
    evidence_pack jsonb DEFAULT '{}'::jsonb,
    triage_report jsonb DEFAULT '{}'::jsonb,
    root_cause_analysis jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    UNIQUE(task_id)
);

-- 3. Agent Events Table: Logs immutable transitions with microsecond resolution
CREATE TABLE IF NOT EXISTS public.agent_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES public.agent_sessions(id) ON DELETE CASCADE,
    from_state text NOT NULL,
    to_state text NOT NULL,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb,
    timestamp timestamptz(6) DEFAULT clock_timestamp()
);

-- 4. Plans Table: Stores multi-step action plans produced by Planner agents
CREATE TABLE IF NOT EXISTS public.plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES public.agent_sessions(id) ON DELETE CASCADE,
    task_id uuid NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    version int NOT NULL DEFAULT 1,
    status text NOT NULL DEFAULT 'draft',
    steps jsonb DEFAULT '[]'::jsonb,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- 5. Executions Table: Records step-by-step tool invocations and outcomes
CREATE TABLE IF NOT EXISTS public.executions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES public.agent_sessions(id) ON DELETE CASCADE,
    plan_id uuid NOT NULL REFERENCES public.plans(id) ON DELETE CASCADE,
    step_index int NOT NULL DEFAULT 0,
    tool_name text NOT NULL,
    tool_input jsonb DEFAULT '{}'::jsonb,
    tool_output jsonb DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'pending',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- Indexes for foreign key lookup performance
CREATE INDEX IF NOT EXISTS idx_tasks_workspace_finding ON public.tasks(workspace_id, finding_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_task ON public.agent_sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_workspace ON public.agent_sessions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_session ON public.agent_events(session_id);
CREATE INDEX IF NOT EXISTS idx_plans_session ON public.plans(session_id);
CREATE INDEX IF NOT EXISTS idx_executions_session_plan ON public.executions(session_id, plan_id);

-- Enable RLS
ALTER TABLE public.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.executions ENABLE ROW LEVEL SECURITY;

-- RLS Policies
DROP POLICY IF EXISTS "Users can view workspace tasks" ON public.tasks;
CREATE POLICY "Users can view workspace tasks"
    ON public.tasks FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.workspace_members
            WHERE workspace_id = public.tasks.workspace_id
            AND user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users can view workspace agent_sessions" ON public.agent_sessions;
CREATE POLICY "Users can view workspace agent_sessions"
    ON public.agent_sessions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.workspace_members
            WHERE workspace_id = public.agent_sessions.workspace_id
            AND user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users can view session agent_events" ON public.agent_events;
CREATE POLICY "Users can view session agent_events"
    ON public.agent_events FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.agent_sessions
            JOIN public.workspace_members ON public.agent_sessions.workspace_id = public.workspace_members.workspace_id
            WHERE public.agent_sessions.id = public.agent_events.session_id
            AND public.workspace_members.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users can view workspace plans" ON public.plans;
CREATE POLICY "Users can view workspace plans"
    ON public.plans FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.agent_sessions
            JOIN public.workspace_members ON public.agent_sessions.workspace_id = public.workspace_members.workspace_id
            WHERE public.agent_sessions.id = public.plans.session_id
            AND public.workspace_members.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users can view workspace executions" ON public.executions;
CREATE POLICY "Users can view workspace executions"
    ON public.executions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.agent_sessions
            JOIN public.workspace_members ON public.agent_sessions.workspace_id = public.workspace_members.workspace_id
            WHERE public.agent_sessions.id = public.executions.session_id
            AND public.workspace_members.user_id = auth.uid()
        )
    );
