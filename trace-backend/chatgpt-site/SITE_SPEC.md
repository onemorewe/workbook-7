# ClosePaw Trace Dashboard — ChatGPT Site spec

Build an owner-only ChatGPT Site named **ClosePaw Trace Dashboard**.

## Purpose
Display remote hands-free trace events stored in Supabase. The Android app never reads from this Site. It writes to the network-reachable, authenticated write-only Supabase Edge Function `trace-ingest`; the Site is only the private read/dashboard surface.

## Access
- Site audience: owner only.
- Do not expose a public trace-read endpoint.
- Store `TRACE_READ_URL` and a distinct `TRACE_READ_TOKEN` as server-only Site secrets. Only the Edge Functions hold `SUPABASE_SERVICE_ROLE_KEY`.
- All Supabase reads must happen server-side through authenticated `trace-read`. Require platform-authenticated identity on every dashboard API route.

## Dashboard UI
- Default view: events from the last 12 hours, newest first.
- Group by `session_id`; if absent, group by a rolling 5-minute window per `device_id`.
- Columns/cards: time, stage, message, app version, device, session.
- Stage badges for relay, wake, stt, vad, transcript, intent, agent, tool, trace, error.
- Filters: time range, stage, session, free-text search.
- Session detail view: chronological timeline with milliseconds where available.
- Highlight `error`, failed tool results, `NOT_READY`, retries, and gaps longer than 5 seconds.
- Add a compact pipeline summary at top: Wake → STT → VAD → Intent → Agent → Tool, showing last known status and latency between stages.
- Add Refresh button and auto-refresh every 5 seconds while the tab is visible.
- No edit/delete controls in the first version.

## Data
Read from `public.trace_events` ordered by `received_at desc`.
Limit ordinary queries to 2000 rows. Fetch one session separately when opened.

## Security
- Never send service-role credentials to the browser.
- Escape all event text before rendering.
- Do not execute HTML, markdown, URLs, scripts, or tool payloads contained in trace messages.
- Treat all trace strings as untrusted data.

## Desired future addition
A button to copy a session as JSON for debugging, generated server-side and returned only to the authenticated owner.
