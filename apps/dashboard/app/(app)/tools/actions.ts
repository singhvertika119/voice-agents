"use server";

import { createClient } from "@supabase/supabase-js";
import { revalidatePath } from "next/cache";
import { supabaseServer } from "@/lib/supabase/server";
import { assertPublicHttps, encryptSecret, sign } from "@/lib/server-security";

export type ToolState = { ok: boolean; message: string; at: number } | null;
const fail = (message: string): ToolState => ({ ok: false, message, at: Date.now() });

const TYPES = ["string", "number", "boolean"];

// Parameters are typed in as lines: name | type | description | required  (for example: order_id | string | The order number | yes)
function parseParams(text: string): { schema: Record<string, unknown>; error?: string } {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const raw of text.split("\n").map((l) => l.trim()).filter(Boolean)) {
    const [name, type = "string", description = "", req = "yes"] = raw.split("|").map((x) => x.trim());
    if (!/^[a-z][a-z0-9_]{0,30}$/.test(name)) return { schema: {}, error: `"${name}" is not a valid name. Use lowercase letters, numbers and underscores.` };
    if (!TYPES.includes(type)) return { schema: {}, error: `Type for ${name} must be string, number or boolean.` };
    properties[name] = { type, description };
    if (/^(y|yes|true|required)$/i.test(req)) required.push(name);
  }
  return { schema: { type: "object", properties, required } };
}

export async function addTool(_prev: ToolState, formData: FormData): Promise<ToolState> {
  const supabase = await supabaseServer();
  const { data: m } = await supabase.from("tenant_members").select("tenant_id,role").limit(1).single();
  if (!m || !["owner", "admin", "editor"].includes(m.role)) return fail("You do not have permission to add tools.");
  const name = String(formData.get("name") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const endpoint = String(formData.get("endpoint") ?? "").trim();
  if (!/^[a-z][a-z0-9_]{2,40}$/.test(name)) return fail("Name: use lowercase letters, numbers and underscores, at least 3 characters (for example check_order_status).");
  if (description.length < 15) return fail("Describe in a sentence when the agent should use this tool. The agent reads it to decide.");
  const bad = await assertPublicHttps(endpoint);
  if (bad) return fail(bad);
  const { schema, error } = parseParams(String(formData.get("params") ?? ""));
  if (error) return fail(error);
  const secret = String(formData.get("secret") ?? "").trim();
  const authHeader = String(formData.get("auth_header") ?? "").trim();
  if (secret && !/^[A-Za-z][A-Za-z0-9-]{1,40}$/.test(authHeader || "Authorization")) return fail("Header name can only have letters, numbers and dashes.");

  const { data: tool, error: insErr } = await supabase
    .from("tools")
    .insert({
      tenant_id: m.tenant_id, name, description, endpoint, parameters: schema,
      method: formData.get("method") === "GET" ? "GET" : "POST",
      auth_header: secret ? authHeader || "Authorization" : null,
      timeout_ms: Math.min(5000, Math.max(500, Number(formData.get("timeout_ms")) || 4000)),
      requires_confirmation: formData.get("requires_confirmation") === "on",
      idempotent: formData.get("idempotent") === "on",
      filler_phrase: String(formData.get("filler_phrase") ?? "").trim() || null,
    })
    .select("id")
    .single();
  if (insErr || !tool) return fail(insErr?.message.includes("duplicate") ? "You already have a tool with that name." : "Could not add the tool. " + (insErr?.message ?? ""));

  if (secret) {
    // The credential is encrypted here and can be decrypted only by the call worker. The browser never gets it back.
    const admin = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
    const { error: sErr } = await admin.from("tool_secrets").insert({ tool_id: tool.id, tenant_id: m.tenant_id, secret_enc: encryptSecret(secret) });
    if (sErr) {
      await supabase.from("tools").delete().eq("id", tool.id);
      return fail("Could not store the credential safely, so the tool was not added.");
    }
  }
  revalidatePath("/tools");
  return { ok: true, message: "Tool added. Open an agent, go to Tools and tick it to let that agent use it.", at: Date.now() };
}

export async function setToolEnabled(id: string, enabled: boolean) {
  const supabase = await supabaseServer();
  await supabase.from("tools").update({ enabled }).eq("id", id);
  revalidatePath("/tools");
}

export async function deleteTool(id: string) {
  const supabase = await supabaseServer();
  await supabase.from("tools").delete().eq("id", id);
  revalidatePath("/tools");
}

// "Test": send a sample request exactly the way a call would (same safety checks and signature) and show what came back.
export async function testTool(id: string, _prev: ToolState, formData: FormData): Promise<ToolState> {
  const supabase = await supabaseServer();
  const { data: t } = await supabase.from("tools").select("*").eq("id", id).single();
  if (!t) return fail("Tool not found.");
  const bad = await assertPublicHttps(t.endpoint);
  if (bad) return fail(bad);
  let args: Record<string, unknown> = {};
  const raw = String(formData.get("sample") ?? "").trim();
  if (raw) {
    try {
      args = JSON.parse(raw);
    } catch {
      return fail('The sample must be JSON, for example {"order_id": "4821"}.');
    }
  }
  let secret: string | null = null;
  if (t.auth_header) {
    const admin = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
    const { data: s } = await admin.from("tool_secrets").select("secret_enc").eq("tool_id", id).single();
    if (s) {
      const { createDecipheriv } = await import("node:crypto");
      const key = Buffer.from(process.env.TOOL_SECRET_KEY ?? "", "base64");
      const buf = Buffer.from(s.secret_enc, "base64");
      const d = createDecipheriv("aes-256-gcm", key, buf.subarray(0, 12));
      d.setAuthTag(buf.subarray(buf.length - 16));
      secret = Buffer.concat([d.update(buf.subarray(12, buf.length - 16)), d.final()]).toString("utf8");
    }
  }
  const body = JSON.stringify(args);
  const ts = String(Math.floor(Date.now() / 1000));
  const headers: Record<string, string> = { "User-Agent": "VoiceAgentsGateway/0.1", "Idempotency-Key": `test:${Date.now()}`, "X-VP-Timestamp": ts, "Content-Type": "application/json" };
  if (secret) {
    headers["X-VP-Signature"] = sign(secret, ts, body);
    if (t.auth_header) headers[t.auth_header] = secret;
  }
  const started = Date.now();
  try {
    const url = new URL(t.endpoint);
    if (t.method === "GET") Object.entries(args).forEach(([k, v]) => url.searchParams.set(k, String(v)));
    const res = await fetch(url, { method: t.method, headers, body: t.method === "GET" ? undefined : body, redirect: "manual", signal: AbortSignal.timeout(t.timeout_ms) });
    const text = (await res.text()).slice(0, 300);
    const ms = Date.now() - started;
    return { ok: res.ok, at: Date.now(), message: `${res.ok ? "Worked" : "The system answered with an error"} (${res.status}, ${ms} ms). ${text ? "It said: " + text : ""}` };
  } catch (e) {
    const timedOut = e instanceof Error && (e.name === "TimeoutError" || e.name === "AbortError");
    return fail(timedOut ? `No answer within ${t.timeout_ms / 1000} seconds. A caller would hear an apology and a callback offer.` : "Could not reach the system. Check the address.");
  }
}
