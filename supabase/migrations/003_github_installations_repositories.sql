-- Migration 003 — GitHub Installations / Repositories

CREATE TABLE IF NOT EXISTS public.github_installations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    github_installation_id bigint NOT NULL UNIQUE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.repositories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    github_installation_id uuid NOT NULL REFERENCES public.github_installations(id) ON DELETE CASCADE,
    github_repo_id bigint NOT NULL,
    owner text NOT NULL,
    name text NOT NULL,
    default_branch text NOT NULL,
    status text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    UNIQUE(workspace_id, github_repo_id)
);

-- Enable RLS
ALTER TABLE public.github_installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.repositories ENABLE ROW LEVEL SECURITY;

-- GitHub Installations RLS
-- Who: Authenticated users assigned to the linked workspace
-- Why: The UI needs to know if the workspace has connected GitHub to render the "Connect GitHub" vs "Select Repo" state.
-- Type: User-facing operation
-- Note: INSERT, UPDATE, DELETE are omitted. The installation lifecycle is managed entirely by the trusted server processing GitHub webhooks/callbacks.
DROP POLICY IF EXISTS "Users can view workspace github installations" ON public.github_installations;
CREATE POLICY "Users can view workspace github installations" 
    ON public.github_installations 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.workspace_members 
            WHERE workspace_id = public.github_installations.workspace_id 
            AND user_id = auth.uid()
        )
    );

-- Repositories RLS
-- Who: Authenticated users assigned to the linked workspace
-- Why: The UI needs to render the repository details (name, owner, status) for the connected Stage 0 repository.
-- Type: User-facing operation
-- Note: INSERT, UPDATE, DELETE are omitted. Repository data is synchronized entirely by the trusted server communicating with the GitHub API.
DROP POLICY IF EXISTS "Users can view workspace repositories" ON public.repositories;
CREATE POLICY "Users can view workspace repositories" 
    ON public.repositories 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.workspace_members 
            WHERE workspace_id = public.repositories.workspace_id 
            AND user_id = auth.uid()
        )
    );
