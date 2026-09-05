create extension if not exists pgcrypto;

create table if not exists public.trace_events (
  id uuid primary key default gen_random_uuid(),
  received_at timestamptz not null default now(),
  device_id text not null,
  app_version text,
  session_id text,
  stage text not null,
  message text not null,
  event_ts bigint,
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists trace_events_received_at_idx
  on public.trace_events (received_at desc);
create index if not exists trace_events_session_id_idx
  on public.trace_events (session_id, received_at);
create index if not exists trace_events_stage_idx
  on public.trace_events (stage, received_at desc);

alter table public.trace_events enable row level security;

-- Deliberately create NO anon/authenticated SELECT policy.
-- The Android app writes only through the trace-ingest Edge Function.
-- The private dashboard reads server-side with the Supabase service-role secret.
-- This keeps trace contents unreadable through the public project API.
