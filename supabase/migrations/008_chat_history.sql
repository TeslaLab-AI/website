-- Migration 008 — Persistent Chat History

CREATE TABLE IF NOT EXISTS public.chat_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id uuid NOT NULL REFERENCES public.repositories(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    references jsonb,
    created_at timestamptz DEFAULT now()
);

-- Enable RLS
ALTER TABLE public.chat_history ENABLE ROW LEVEL SECURITY;

-- Policy: Users can view chat history for repositories in their workspaces
DROP POLICY IF EXISTS "Users can view workspace chat history" ON public.chat_history;
CREATE POLICY "Users can view workspace chat history" 
    ON public.chat_history 
    FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.repositories r
            JOIN public.workspace_members wm ON r.workspace_id = wm.workspace_id
            WHERE r.id = public.chat_history.repository_id 
            AND wm.user_id = auth.uid()
        )
    );
