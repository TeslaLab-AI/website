-- Migration 005 — Scans and Findings

CREATE TYPE public.scan_status AS ENUM ('in_progress', 'completed', 'failed');
CREATE TYPE public.finding_category AS ENUM ('bugs', 'dependencies', 'security', 'testing');
CREATE TYPE public.finding_severity AS ENUM ('critical', 'high', 'medium', 'low');

-- Scans table stores the status and metadata for each repository analysis process
CREATE TABLE IF NOT EXISTS public.scans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id uuid NOT NULL REFERENCES public.repositories(id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    status public.scan_status NOT NULL DEFAULT 'in_progress',
    started_at timestamptz DEFAULT now(),
    completed_at timestamptz
);

-- Scan Findings table stores the specific issues identified during a scan
CREATE TABLE IF NOT EXISTS public.scan_findings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id uuid NOT NULL REFERENCES public.scans(id) ON DELETE CASCADE,
    category public.finding_category NOT NULL,
    severity public.finding_severity NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    file_path text,
    line_number int
);

-- Enable RLS
ALTER TABLE public.scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scan_findings ENABLE ROW LEVEL SECURITY;

-- Scans RLS: Ensure users can only see scans belonging to workspaces they are members of
DROP POLICY IF EXISTS "Users can view workspace scans" ON public.scans;
CREATE POLICY "Users can view workspace scans" 
    ON public.scans 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.workspace_members 
            WHERE workspace_id = public.scans.workspace_id 
            AND user_id = auth.uid()
        )
    );

-- Scan Findings RLS: Ensure users can only see findings for scans in their authorized workspaces
DROP POLICY IF EXISTS "Users can view workspace scan findings" ON public.scan_findings;
CREATE POLICY "Users can view workspace scan findings" 
    ON public.scan_findings 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.scans
            JOIN public.workspace_members ON public.scans.workspace_id = public.workspace_members.workspace_id
            WHERE public.scans.id = public.scan_findings.scan_id
            AND public.workspace_members.user_id = auth.uid()
        )
    );
