-- CI-only empty Postgres emulates the built-in Supabase roles. Never run on a real project.
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
grant usage on schema public to anon, authenticated, service_role;
