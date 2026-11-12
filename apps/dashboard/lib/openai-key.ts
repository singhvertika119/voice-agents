// Each workspace's own OpenAI key (bring your own key, docs/decision.md D-124). Server code only: the key is read
// with the service key and decrypted here, and is never sent to the browser. The knowledge chat uses it only when
// the owner chose "everything" (D-125); otherwise, or without a working key, it uses the free Groq model.
import { decryptSecret } from "@/lib/server-security";
import { adminClient } from "@/lib/supabase/admin";

export type KeyStatus = "ok" | "no_credits" | "invalid" | "unchecked";
export type KeyUse = "calls" | "everything";
export type KeyCheck = KeyStatus | "unreachable";
type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

const OPENAI_URL = "https://api.openai.com/v1/chat/completions";
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const FREE_MODEL = process.env.FREE_LLM_MODEL || "openai/gpt-oss-120b";
const RETRY_AFTER_MS = 60 * 60 * 1000;   // a key marked "no credits" is tried again after an hour (same as the worker)

// What OpenAI says about a key. One tiny request (a 1-word reply, a tiny fraction of a cent on the key's own
// account), because only a real request shows whether the account has credits.
export async function checkOpenAIKey(key: string): Promise<KeyCheck> {
  try {
    const r = await fetch(OPENAI_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: "gpt-4o-mini", max_tokens: 1, messages: [{ role: "user", content: "ok" }] }),
      signal: AbortSignal.timeout(10000),
      cache: "no-store",
    });
    if (r.ok) return "ok";
    return verdict(r.status, await r.text()) ?? "unreachable";
  } catch {
    return "unreachable";
  }
}

// Same rules as packages/core/vp_core/tenant_keys.py classify(); keep the two in step.
function verdict(status: number, body: string): KeyStatus | null {
  if (status === 401) return "invalid";
  if (status === 429 && /insufficient_quota|credit_balance|billing/.test(body)) return "no_credits";
  return null;
}

type StoredKey = { tenantId: string; key: string; status: KeyStatus; checkedAt: string | null; useFor: KeyUse };

async function loadKey(tenantId: string): Promise<StoredKey | null> {
  const { data, error } = await adminClient().from("tenant_api_keys").select("secret_enc,status,checked_at,use_for")
    .eq("tenant_id", tenantId).eq("provider", "openai").maybeSingle();
  if (error || !data) return null;
  try {
    return { tenantId, key: decryptSecret(data.secret_enc), status: data.status as KeyStatus, checkedAt: data.checked_at, useFor: data.use_for as KeyUse };
  } catch {
    return null;
  }
}

async function saveStatus(tenantId: string, status: KeyStatus) {
  await adminClient().from("tenant_api_keys").update({ status, checked_at: new Date().toISOString() })
    .eq("tenant_id", tenantId).eq("provider", "openai");
}

function worthTrying(k: StoredKey): boolean {
  if (k.status === "invalid") return false;
  if (k.status === "ok" || k.status === "unchecked") return true;
  return !k.checkedAt || Date.now() - new Date(k.checkedAt).getTime() > RETRY_AFTER_MS;
}

// A chat reply: the workspace's OpenAI model when it has a working key, otherwise the free model.
// Throws only when neither can answer.
export async function chatCompletion(tenantId: string, messages: ChatMessage[], opts: { model?: string; temperature?: number; maxTokens: number }): Promise<string> {
  const k = await loadKey(tenantId);
  if (k && k.useFor === "everything" && worthTrying(k)) {
    try {
      const r = await fetch(OPENAI_URL, {
        method: "POST",
        headers: { Authorization: `Bearer ${k.key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model: opts.model ?? "gpt-4o-mini", temperature: opts.temperature ?? 0.2, max_tokens: opts.maxTokens, messages }),
        signal: AbortSignal.timeout(30000),
        cache: "no-store",
      });
      if (r.ok) {
        if (k.status !== "ok") await saveStatus(tenantId, "ok");
        return (await r.json()).choices?.[0]?.message?.content?.trim() ?? "";
      }
      const v = verdict(r.status, await r.text());
      if (v) await saveStatus(tenantId, v);
    } catch {
      // network problem: fall through to the free model
    }
  }
  const groq = process.env.GROQ_API_KEY;
  if (!groq) throw new Error("no model available");
  const r = await fetch(GROQ_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${groq}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: FREE_MODEL, temperature: opts.temperature ?? 0.2, reasoning_effort: "low",
      max_completion_tokens: opts.maxTokens + 400,   // gpt-oss thinks before it answers, and that counts too
      messages,
    }),
    signal: AbortSignal.timeout(30000),
    cache: "no-store",
  });
  if (!r.ok) throw new Error("free model failed");
  return (await r.json()).choices?.[0]?.message?.content?.trim() ?? "";
}
