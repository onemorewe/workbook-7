-- Additive: preserve existing trace rows and migration history.
alter table public.trace_events
  add column if not exists client_event_id uuid,
  add column if not exists run_id text,
  add column if not exists seq bigint,
  add column if not exists level text not null default 'info',
  add column if not exists duration_ms bigint;

create unique index if not exists trace_events_device_event_idx
  on public.trace_events(device_id, client_event_id);
create index if not exists trace_events_run_idx
  on public.trace_events(device_id, run_id, received_at, id);
create index if not exists trace_events_cursor_idx
  on public.trace_events(received_at desc, id desc);

alter table public.trace_events enable row level security;
alter table public.trace_events force row level security;
revoke all on public.trace_events from public, anon, authenticated;
grant select, insert on public.trace_events to service_role;

comment on table public.trace_events is
  'Private untrusted operational traces. Android uses authenticated ingest only. No public read policies.';
