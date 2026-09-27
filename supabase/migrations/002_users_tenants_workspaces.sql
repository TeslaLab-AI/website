-- Migration 002 — Users / Tenants / Workspaces

CREATE TABLE IF NOT EXISTS public.workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    plan text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.workspace_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at timestamptz DEFAULT now(),
    UNIQUE(workspace_id, user_id)
);

-- Enable RLS
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_members ENABLE ROW LEVEL SECURITY;

-- Workspaces RLS
-- Who: Authenticated users
-- Why: Users need to load their assigned workspace contexts in the dashboard UI.
-- Type: User-facing operation
-- Note: UPDATE, DELETE, and INSERT are omitted. Workspace lifecycle is a trusted server-side operation.
DROP POLICY IF EXISTS "Users can view assigned workspaces" ON public.workspaces;
CREATE POLICY "Users can view assigned workspaces" 
    ON public.workspaces 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.workspace_members 
            WHERE workspace_id = public.workspaces.id 
            AND user_id = auth.uid()
        )
    );

-- Workspace Members RLS
-- Who: Authenticated users
-- Why: Users need to verify their own membership to the workspace (e.g., in middleware or dashboard layout).
-- Type: User-facing operation
-- Note: Users cannot view other members. INSERT, UPDATE, and DELETE are omitted.
-- Membership provisioning is a trusted server-side operation.
DROP POLICY IF EXISTS "Users can view own memberships" ON public.workspace_members;
CREATE POLICY "Users can view own memberships" 
    ON public.workspace_members 
    FOR SELECT 
    USING ( user_id = auth.uid() );
