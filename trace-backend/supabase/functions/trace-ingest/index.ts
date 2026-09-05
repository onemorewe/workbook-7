import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "content-type,x-closepaw-device,x-closepaw-version",
  "access-control-allow-methods": "POST,OPTIONS",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const length = Number(req.headers.get("content-length") || "0");
  if (length > 16_384) return json({ error: "payload_too_large" }, 413);

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }

  const stage = clean(body.stage, 80);
  const message = clean(body.message, 8_000);
  if (!stage || !message) return json({ error: "missing_stage_or_message" }, 400);

  const deviceId = clean(req.headers.get("x-closepaw-device") || body.device_id, 128) || "unknown";
  const appVersion = clean(req.headers.get("x-closepaw-version") || body.app_version, 128);
  const sessionId = clean(body.session_id, 256);
  const eventTs = typeof body.ts === "number" ? Math.trunc(body.ts) : null;
  const metadata = isPlainObject(body.metadata) ? body.metadata : {};

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceKey) return json({ error: "server_not_configured" }, 500);

  const db = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { error } = await db.from("trace_events").insert({
    device_id: deviceId,
    app_version: appVersion || null,
    session_id: sessionId || null,
    stage,
    message,
    event_ts: eventTs,
    metadata,
  });

  if (error) return json({ error: "insert_failed" }, 500);
  return json({ ok: true }, 202);
});

function clean(value: unknown, max: number): string {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, max);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, "content-type": "application/json; charset=utf-8" },
  });
}
