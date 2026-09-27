-- Migration 006 — Code Intelligence Schema (pgvector)

-- Enable the pgvector extension to support vector embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Create Repository Snapshots table
-- A snapshot represents a specific point in time (commit) for a repository
CREATE TABLE IF NOT EXISTS public.repository_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id uuid NOT NULL REFERENCES public.repositories(id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    commit_sha text NOT NULL,
    created_at timestamptz DEFAULT now(),
    
    -- Ensure we only snapshot a commit once per repository
    UNIQUE(repository_id, commit_sha)
);

-- 2. Create Code Chunks table
-- Stores individual files or chunks of files and their semantic embeddings
CREATE TABLE IF NOT EXISTS public.code_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id uuid NOT NULL REFERENCES public.repository_snapshots(id) ON DELETE CASCADE,
    
    file_path text NOT NULL,
    content text NOT NULL,
    language text,
    
    -- OpenAI text-embedding-3-small uses 1536 dimensions
    -- text-embedding-ada-002 uses 1536 dimensions
    -- adjust dimensions if using a different model
    embedding vector(1536),
    
    created_at timestamptz DEFAULT now()
);

-- Create an HNSW index for fast semantic search over the embeddings
-- This speeds up vector similarity queries significantly
CREATE INDEX ON public.code_chunks USING hnsw (embedding vector_cosine_ops);

-- Enable RLS
ALTER TABLE public.repository_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.code_chunks ENABLE ROW LEVEL SECURITY;

-- Repository Snapshots RLS
DROP POLICY IF EXISTS "Users can view workspace snapshots" ON public.repository_snapshots;
CREATE POLICY "Users can view workspace snapshots" 
    ON public.repository_snapshots 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.workspace_members 
            WHERE workspace_id = public.repository_snapshots.workspace_id 
            AND user_id = auth.uid()
        )
    );

-- Code Chunks RLS
DROP POLICY IF EXISTS "Users can view workspace code chunks" ON public.code_chunks;
CREATE POLICY "Users can view workspace code chunks" 
    ON public.code_chunks 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.repository_snapshots
            JOIN public.workspace_members ON public.repository_snapshots.workspace_id = public.workspace_members.workspace_id
            WHERE public.repository_snapshots.id = public.code_chunks.snapshot_id
            AND public.workspace_members.user_id = auth.uid()
        )
    );
