\set ON_ERROR_STOP on
begin;
-- Run on an isolated CI database AFTER the actual migrations.
do $$
begin
  assert (select relrowsecurity and relforcerowsecurity from pg_class where oid='public.trace_events'::regclass), 'RLS must be enabled and forced';
  assert not exists (select 1 from pg_policies where schemaname='public' and tablename='trace_events'), 'No client policies allowed';
  assert not has_table_privilege('anon','public.trace_events','SELECT,INSERT,UPDATE,DELETE'), 'anon has privileges';
  assert not has_table_privilege('authenticated','public.trace_events','SELECT,INSERT,UPDATE,DELETE'), 'authenticated has privileges';
  assert has_table_privilege('service_role','public.trace_events','SELECT') and has_table_privilege('service_role','public.trace_events','INSERT'), 'backend access missing';
end $$;
set local role anon;
do $$ begin
  begin perform * from public.trace_events; raise exception 'anon SELECT unexpectedly succeeded'; exception when insufficient_privilege then null; end;
  begin insert into public.trace_events(device_id,stage,message) values ('x','x','x'); raise exception 'anon INSERT unexpectedly succeeded'; exception when insufficient_privilege then null; end;
  begin update public.trace_events set message='x'; raise exception 'anon UPDATE unexpectedly succeeded'; exception when insufficient_privilege then null; end;
  begin delete from public.trace_events; raise exception 'anon DELETE unexpectedly succeeded'; exception when insufficient_privilege then null; end;
end $$;
set local role authenticated;
do $$ begin
  begin perform * from public.trace_events; raise exception 'authenticated SELECT unexpectedly succeeded'; exception when insufficient_privilege then null; end;
  begin insert into public.trace_events(device_id,stage,message) values ('x','x','x'); raise exception 'authenticated INSERT unexpectedly succeeded'; exception when insufficient_privilege then null; end;
  begin update public.trace_events set message='x'; raise exception 'authenticated UPDATE unexpectedly succeeded'; exception when insufficient_privilege then null; end;
  begin delete from public.trace_events; raise exception 'authenticated DELETE unexpectedly succeeded'; exception when insufficient_privilege then null; end;
end $$;
set local role service_role;
insert into public.trace_events(device_id,client_event_id,stage,message)
values ('test-phone','11111111-1111-1111-1111-111111111111','wake','original');
insert into public.trace_events(device_id,client_event_id,stage,message)
values ('test-phone','11111111-1111-1111-1111-111111111111','wake','duplicate')
on conflict(device_id,client_event_id) do nothing;
do $$ begin
  assert (select count(*)=1 from public.trace_events where device_id='test-phone'), 'retry must deduplicate';
  assert (select message='original' from public.trace_events where device_id='test-phone'), 'retry must not mutate';
end $$;
rollback;
