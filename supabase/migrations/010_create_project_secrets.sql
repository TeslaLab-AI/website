-- Per-project encrypted secrets (env vars) for the Deployment Engine.
-- Values are encrypted by the backend (Fernet) BEFORE they reach this table.
-- NOTE: rename this file to match the numbering/timestamp style of the other
-- files in supabase/migrations/.

create table if not exists public.project_secrets (
    id               uuid primary key default gen_random_uuid(),
    tenant_id        text not null,
    project_id       text not null,
    key              text not null,
    value_encrypted  text not null,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint project_secrets_key_format check (key ~ '^[A-Za-z_][A-Za-z0-9_]*$'),
    constraint project_secrets_unique unique (tenant_id, project_id, key)
);

-- If your projects table uses uuid ids, change tenant_id / project_id to uuid
-- and add foreign keys to it.

create index if not exists project_secrets_tenant_project_idx
    on public.project_secrets (tenant_id, project_id);

-- Row Level Security: deny everything by default.
-- No policies are created on purpose, so anon/authenticated users can never
-- read this table. The backend uses the service role, which bypasses RLS.
alter table public.project_secrets enable row level security;

revoke all on public.project_secrets from anon, authenticated;