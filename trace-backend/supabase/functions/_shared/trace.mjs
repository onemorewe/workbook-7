// Web-standard handlers shared by Supabase/Deno and Node contract tests.
export const MAX_BYTES = 65_536;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ID = /^[a-zA-Z0-9_.:-]{1,256}$/;
const HASH = /^[0-9a-f]{64}$/;
const SECRET_KEY = /(?:authorization|cookie|password|passwd|secret|credential|(?:access|refresh|id|device|write|read)?[_ -]?token|api[_ -]?key|service[_ -]?role|keystore|private[_ -]?key)/i;
export class HttpError extends Error {
  constructor(status, code) { super(code); this.status = status; }
}
export function json(value, status = 200) {
  return new Response(JSON.stringify(value), {status, headers: {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store', 'x-content-type-options': 'nosniff',
  }});
}
export async function sha256(value) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(x => x.toString(16).padStart(2, '0')).join('');
}
function equalHash(a, b) {
  if (!HASH.test(a ?? '') || !HASH.test(b ?? '')) return false;
  let difference = 0;
  for (let i = 0; i < 64; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}
async function authenticate(req, env, scope) {
  let entries;
  try { entries = JSON.parse(env(scope === 'write' ? 'TRACE_WRITE_TOKENS_JSON' : 'TRACE_READ_TOKENS_JSON') || 'null'); }
  catch { throw new HttpError(503, 'auth_not_configured'); }
  if (!Array.isArray(entries) || !entries.length || entries.some(e => !e || !HASH.test(e.sha256) || (scope === 'write' && !ID.test(e.device_id)))) throw new HttpError(503, 'auth_not_configured');
  const match = /^Bearer ([A-Za-z0-9_-]{32,256})$/.exec(req.headers.get('authorization') || '');
  if (!match) throw new HttpError(401, 'unauthorized');
  const digest = await sha256(match[1]);
  const entry = entries.find(e => equalHash(digest, e.sha256));
  if (!entry || (entry.expires_at && (!Number.isFinite(Date.parse(entry.expires_at)) || Date.parse(entry.expires_at) <= Date.now()))) throw new HttpError(401, 'unauthorized');
  return { ...entry, presentedToken: match[1] };
}
export function redactText(value, known = []) {
  let text = value;
  for (const secret of known.filter(x => typeof x === 'string' && x.length >= 12)) text = text.split(secret).join('[REDACTED]');
  return text
    .replace(/-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)/g, '[REDACTED PRIVATE KEY]')
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, 'Bearer [REDACTED]')
    .replace(/\b(?:sk-|sb_secret_|sb_publishable_|ghp_|github_pat_|sbp_)[A-Za-z0-9_-]{8,}/g, '[REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[REDACTED JWT]')
    .replace(/\b(?:postgres(?:ql)?|https?):\/\/[^\s/:]+:[^\s@]+@/gi, '[REDACTED CREDENTIALS]@')
    .replace(/((?:["']?)(?:authorization|cookie|password|secret|credential|(?:access|refresh|id|device|write|read)[_ -]?token|api[_ -]?key|service[_ -]?role(?:[_ -]?key)?)(?:["']?)\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s&,;}]+)/gi, '$1[REDACTED]');
}
export function redact(value, known = [], depth = 0) {
  if (depth > 12) return '[DEPTH LIMIT]';
  if (typeof value === 'string') {
    // Some upstream trace fields contain serialized JSON, not objects.
    if (/^\s*[\[{]/.test(value)) {
      try { return JSON.stringify(redact(JSON.parse(value), known, depth + 1)); } catch { /* free text */ }
    }
    return redactText(value, known).slice(0, 12_000);
  }
  if (Array.isArray(value)) return value.slice(0, 128).map(v => redact(v, known, depth + 1));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).slice(0, 128).map(([k,v]) => [redactText(k, known).slice(0,128), SECRET_KEY.test(k) ? '[REDACTED]' : redact(v, known, depth + 1)]));
  return value;
}
async function readBody(req) {
  if (!/^application\/json(?:\s*;|$)/i.test(req.headers.get('content-type') || '')) throw new HttpError(415, 'json_required');
  if (Number(req.headers.get('content-length')) > MAX_BYTES) throw new HttpError(413, 'payload_too_large');
  if (!req.body) throw new HttpError(400, 'invalid_json');
  const reader = req.body.getReader(); const chunks = []; let length = 0;
  try {
    while (true) {
      const {done, value} = await reader.read(); if (done) break;
      length += value.byteLength;
      if (length > MAX_BYTES) { await reader.cancel(); throw new HttpError(413, 'payload_too_large'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const data = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.length; }
  try { return JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(data)); }
  catch { throw new HttpError(400, 'invalid_json'); }
}
function optionalId(v) {
  if (v == null || v === '') return null;
  if (typeof v !== 'string' || !ID.test(v)) throw new HttpError(400, 'invalid_identifier');
  return v;
}
function integer(v, max = Number.MAX_SAFE_INTEGER) {
  if (v == null) return null;
  if (!Number.isSafeInteger(v) || v < 0 || v > max) throw new HttpError(400, 'invalid_integer');
  return v;
}
function configuration(env) {
  const url = env('SUPABASE_URL'); const key = env('SUPABASE_SERVICE_ROLE_KEY');
  if (!url || !key) throw new HttpError(503, 'server_not_configured');
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' && !['localhost','127.0.0.1','kong'].includes(parsed.hostname)) throw new HttpError(503, 'server_not_configured');
  return { url: parsed.origin, key };
}
function dbHeaders(key) { return { apikey:key, authorization:`Bearer ${key}`, 'content-type':'application/json' }; }
function safe(handler) {
  return async req => {
    try { return await handler(req); }
    catch(e) { return json({error:e instanceof HttpError ? e.message : 'request_failed'}, e instanceof HttpError ? e.status : 503); }
  };
}
export function createIngest({env, fetcher = fetch}) {
  return safe(async req => {
    if (req.method !== 'POST') return json({error:'method_not_allowed'}, 405);
    const auth = await authenticate(req, env, 'write');
    const body = await readBody(req);
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new HttpError(400, 'invalid_event');
    if (!UUID.test(body.event_id || '')) throw new HttpError(400, 'event_id_required');
    if (typeof body.stage !== 'string' || !/^[a-zA-Z0-9_.:-]{1,80}$/.test(body.stage)) throw new HttpError(400, 'invalid_stage');
    if (typeof body.message !== 'string' || !body.message.trim() || body.message.length > 12_000) throw new HttpError(400, 'invalid_message');
    if (body.metadata != null && (typeof body.metadata !== 'object' || Array.isArray(body.metadata))) throw new HttpError(400, 'invalid_metadata');
    if (body.app_version != null && (typeof body.app_version !== 'string' || body.app_version.length > 128)) throw new HttpError(400, 'invalid_version');
    const level = body.level ?? 'info';
    if (!['debug','info','warn','error'].includes(level)) throw new HttpError(400, 'invalid_level');
    const {url, key} = configuration(env);
    const known = [key, auth.presentedToken];
    const row = {
      client_event_id:body.event_id.toLowerCase(), device_id:auth.device_id,
      app_version:body.app_version ? redactText(body.app_version, known) : null,
      session_id:redact(optionalId(body.session_id), known), run_id:redact(optionalId(body.run_id), known),
      seq:integer(body.seq), stage:redactText(body.stage, known), level,
      message:redact(body.message, known), event_ts:integer(body.ts, 8_640_000_000_000_000),
      duration_ms:integer(body.duration_ms), metadata:redact(body.metadata ?? {}, known),
    };
    // The same event may be retried after a timeout. Never overwrite an accepted event.
    const response = await fetcher(`${url}/rest/v1/trace_events?on_conflict=device_id,client_event_id`, {
      method:'POST', headers:{...dbHeaders(key), prefer:'resolution=ignore-duplicates,return=minimal'},
      body:JSON.stringify(row), signal:AbortSignal.timeout(8_000),
    });
    if (!response.ok) throw new HttpError(503, 'insert_failed');
    return json({ok:true, event_id:body.event_id.toLowerCase()}, 202);
  });
}
export function readQuery(params, now = Date.now()) {
  const query = new URLSearchParams({select:'*', order:'received_at.desc,id.desc'});
  const limit = Number(params.get('limit') ?? 500);
  if (!Number.isInteger(limit) || limit < 1 || limit > 1000) throw new HttpError(400, 'invalid_limit');
  query.set('limit', String(limit));
  const since = params.get('since') || new Date(now - 12*3600_000).toISOString();
  if (!Number.isFinite(Date.parse(since))) throw new HttpError(400, 'invalid_since');
  query.append('received_at', `gte.${new Date(since).toISOString()}`);
  const until = params.get('until');
  if (until) {
    if (!Number.isFinite(Date.parse(until)) || Date.parse(until) < Date.parse(since)) throw new HttpError(400, 'invalid_until');
    query.append('received_at', `lte.${new Date(until).toISOString()}`);
  }
  for (const field of ['device_id','session_id','run_id','stage','level']) {
    const value = params.get(field);
    if (value) query.set(field, `eq.${optionalId(value)}`);
  }
  const search = params.get('q')?.trim();
  if (search) {
    if (search.length > 200) throw new HttpError(400, 'search_too_long');
    // Quoted PostgREST values: commas, parentheses, quotes and wildcard input stay data.
    const literal = search.replace(/[\\%_*]/g, '\\$&').replace(/"/g, '\\"');
    query.set('message', `ilike."%${literal}%"`);
  }
  const cursor = params.get('cursor');
  if (cursor) {
    let c; try { c = JSON.parse(cursor); } catch { throw new HttpError(400, 'invalid_cursor'); }
    // Preserve Postgres microseconds. Date.toISOString() would lose rows within a millisecond.
    if (!c || !UUID.test(c.id || '') || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(c.received_at || '') || !Number.isFinite(Date.parse(c.received_at))) throw new HttpError(400, 'invalid_cursor');
    query.set('or', `(received_at.lt.${c.received_at},and(received_at.eq.${c.received_at},id.lt.${c.id}))`);
  }
  return {query, limit};
}
export function createRead({env, fetcher = fetch}) {
  return safe(async req => {
    if (req.method !== 'GET') return json({error:'method_not_allowed'}, 405);
    await authenticate(req, env, 'read');
    const {query, limit} = readQuery(new URL(req.url).searchParams);
    const {url, key} = configuration(env);
    const response = await fetcher(`${url}/rest/v1/trace_events?${query}`, {headers:dbHeaders(key), signal:AbortSignal.timeout(8_000)});
    if (!response.ok) throw new HttpError(503, 'read_failed');
    const rows = await response.json();
    if (!Array.isArray(rows)) throw new HttpError(503, 'read_failed');
    const last = rows.at(-1);
    return json({events:rows, next_cursor: rows.length === limit && last ? JSON.stringify({received_at:last.received_at,id:last.id}) : null});
  });
}
