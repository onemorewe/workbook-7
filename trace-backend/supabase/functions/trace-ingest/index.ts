import { createIngest } from "../_shared/trace.mjs";

async function tokenRegistry(scope: "write" | "read") {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) return null;

  const response = await fetch(
    `${url}/rest/v1/private_trace_tokens?scope=eq.${scope}&select=token_hash,device_id,expires_at`,
    { headers: { apikey: key, authorization: `Bearer ${key}` } },
  );
  if (!response.ok) return null;

  const rows = await response.json();
  if (!Array.isArray(rows)) return null;
  return JSON.stringify(rows.map((row) => ({
    sha256: row.token_hash,
    device_id: row.device_id,
    expires_at: row.expires_at,
  })));
}

Deno.serve(async (req: Request) => {
  const writeTokens = await tokenRegistry("write");
  const handler = createIngest({
    env: (name: string) => name === "TRACE_WRITE_TOKENS_JSON"
      ? writeTokens
      : Deno.env.get(name),
  });
  return handler(req);
});
