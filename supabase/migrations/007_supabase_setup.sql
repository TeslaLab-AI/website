-- Supabase SQL to enable vector similarity search on the code_chunks table.
-- Please run this exact script in your Supabase SQL Editor.

CREATE OR REPLACE FUNCTION match_code_chunks(
    query_embedding vector(1536),
    match_threshold float,
    match_count int,
    p_repository_id uuid
)
RETURNS TABLE (
    id uuid,
    file_path text,
    content text,
    language text,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.id,
        c.file_path,
        c.content,
        c.language,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM code_chunks c
    JOIN repository_snapshots s ON c.snapshot_id = s.id
    WHERE s.repository_id = p_repository_id
      AND 1 - (c.embedding <=> query_embedding) > match_threshold
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;
