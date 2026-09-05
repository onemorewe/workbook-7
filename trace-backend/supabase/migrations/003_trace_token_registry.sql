create table if not exists public.private_trace_tokens (
  token_hash text primary key check (token_hash ~ '^[0-9a-f]{64}$'),
  scope text not null check (scope in ('write','read')),
  device_id text,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  check ((scope = 'write' and device_id is not null) or (scope = 'read' and device_id is null))
);

alter table public.private_trace_tokens enable row level security;
alter table public.private_trace_tokens force row level security;
revoke all on public.private_trace_tokens from public, anon, authenticated;
grant select on public.private_trace_tokens to service_role;

comment on table public.private_trace_tokens is
  'Private SHA-256 credential registry for trace Edge Functions. Plaintext tokens are never stored.';
