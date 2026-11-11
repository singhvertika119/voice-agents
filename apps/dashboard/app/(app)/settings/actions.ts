"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@supabase/supabase-js";
import { supabaseServer } from "@/lib/supabase/server";
import { toE164 } from "@/lib/phone";
import { adminClient, checkOpenAIKey, type KeyCheck } from "@/lib/openai-key";
import { decryptSecret, encryptSecret } from "@/lib/server-security";

export type FormState = { ok: boolean; message: string } | null;

async function ctx() {
  const supabase = await supabaseServer();
  const { data } = await supabase.from("tenant_members").select("tenant_id,role").limit(1).single();
  return { supabase, tenantId: data?.tenant_id as string | undefined, role: data?.role as string | undefined };
}

const num = (v: FormDataEntryValue | null, min: number, max: number, fallback: number) => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : fallback;
};

export async function saveSettings(_prev: FormState, formData: FormData): Promise<FormState> {
  const { supabase, tenantId, role } = await ctx();
  if (!tenantId || !["owner", "admin"].includes(role ?? "")) return { ok: false, message: "Only an owner or admin can change settings." };
  const days = formData.getAll("days").map(Number).filter((d) => d >= 1 && d <= 7).sort();
  const start = String(formData.get("start") ?? "09:00");
  const end = String(formData.get("end") ?? "19:00");
  if (!/^\d\d:\d\d$/.test(start) || !/^\d\d:\d\d$/.test(end) || start >= end) return { ok: false, message: "Closing time must be after opening time." };
  if (!days.length) return { ok: false, message: "Choose at least one working day." };
  const phone = String(formData.get("handoff_phone") ?? "").replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "");
  if (phone && !/^[6-9]\d{9}$/.test(phone)) return { ok: false, message: "Enter a 10-digit mobile number for your team, or leave it empty." };
  const row = {
    tenant_id: tenantId,
    business_hours: { days, start, end },
    handoff_phone: phone ? `+91${phone}` : null,
    retention_days: num(formData.get("retention_days"), 1, 3650, 90),
    max_concurrent_calls: num(formData.get("max_concurrent_calls"), 1, 500, 5),
    memory_enabled: formData.get("memory_enabled") === "on",
    record_calls: formData.get("record_calls") === "on",
    require_tests_to_publish: formData.get("require_tests") === "on",
    updated_at: new Date().toISOString(),
  };
  let { error } = await supabase.from("tenant_settings").upsert(row);
  if (error && error.message.includes("record_calls")) {
    // Database without the recordings update (0006): save everything else so settings never break.
    const { record_calls: _skip, ...rest } = row;
    void _skip;
    ({ error } = await supabase.from("tenant_settings").upsert(rest));
  }
  if (error) {
    return { ok: false, message: "Could not save. " + (error.message.includes("tenant_settings") ? "The database update for settings has not been applied yet." : error.message) };
  }
  revalidatePath("/settings");
  return { ok: true, message: "Saved." };
}

// "Delete everything about this caller". Runs inside the database so every related record goes in one step.
export async function eraseCaller(_prev: FormState, formData: FormData): Promise<FormState> {
  const { supabase, tenantId, role } = await ctx();
  if (!tenantId || !["owner", "admin"].includes(role ?? "")) return { ok: false, message: "Only an owner or admin can erase a caller's data." };
  if (formData.get("confirm") !== "on") return { ok: false, message: "Tick the box to confirm. This cannot be undone." };
  const phone = toE164(String(formData.get("phone") ?? ""));
  if (!phone) return { ok: false, message: "Enter the caller's 10-digit mobile number, or the full number starting with + for a number outside India." };
  // Audio files are not in the database, so remove them first (the erase function below cannot reach storage).
  const { data: rec } = await supabase.from("calls").select("recording_path").eq("tenant_id", tenantId).eq("caller_number", phone).not("recording_path", "is", null);
  const paths = (rec ?? []).map((r) => r.recording_path as string);
  if (paths.length) {
    const admin = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
    const { error: rmErr } = await admin.storage.from("recordings").remove(paths);
    if (rmErr) return { ok: false, message: "Could not delete the recordings, so nothing was erased. Try again." };
  }
  const { data, error } = await supabase.rpc("erase_caller", { p_tenant: tenantId, p_phone: phone });
  if (error) return { ok: false, message: "Could not erase. " + error.message };
  const r = data as { calls: number; contacts: number; callbacks: number };
  revalidatePath("/calls");
  return {
    ok: true,
    message: `Erased ${r.calls} call${r.calls === 1 ? "" : "s"} with transcripts and ${paths.length} recording${paths.length === 1 ? "" : "s"}, ${r.contacts} saved profile${r.contacts === 1 ? "" : "s"} and ${r.callbacks} callback request${r.callbacks === 1 ? "" : "s"}.`,
  };
}

// ---------------------------------------------------------------- the workspace's own OpenAI key (D-124)
// The key is checked with OpenAI, encrypted here and stored where only server code can read it. It is never shown
// again: Settings shows only its last four characters and whether it works.
const CHECK_MESSAGES: Record<KeyCheck, string> = {
  ok: "Saved. The key works.",
  no_credits: "Saved, but this OpenAI account has no credits left, so the free model is used until you add credits.",
  invalid: "OpenAI did not accept this key. Check that you copied all of it.",
  unchecked: "Saved.",
  unreachable: "Saved, but OpenAI could not be reached to check it. It will be checked on first use.",
};

async function keyAdmin() {
  const { tenantId, role } = await ctx();
  const ok = !!tenantId && ["owner", "admin"].includes(role ?? "");
  return { tenantId, ok };
}

export async function saveOpenAIKey(_prev: FormState, formData: FormData): Promise<FormState> {
  const { tenantId, ok } = await keyAdmin();
  if (!ok || !tenantId) return { ok: false, message: "Only an owner or admin can change the OpenAI key." };
  const key = String(formData.get("openai_key") ?? "").trim();
  if (!/^sk-[A-Za-z0-9_-]{20,}$/.test(key)) return { ok: false, message: "That does not look like an OpenAI key. It starts with sk- and is long." };
  const check = await checkOpenAIKey(key);
  if (check === "invalid") return { ok: false, message: CHECK_MESSAGES.invalid };
  const supabase = await supabaseServer();
  const { data: user } = await supabase.auth.getUser();
  const { error } = await adminClient().from("tenant_api_keys").upsert({
    tenant_id: tenantId, provider: "openai", secret_enc: encryptSecret(key), last4: key.slice(-4),
    status: check === "unreachable" ? "unchecked" : check,
    checked_at: check === "unreachable" ? null : new Date().toISOString(),
    updated_at: new Date().toISOString(), updated_by: user.user?.id ?? null,
  });
  if (error) {
    return { ok: false, message: "Could not save. " + (error.message.includes("tenant_api_keys") ? "The database update for keys (0011) has not been applied yet." : error.message) };
  }
  revalidatePath("/settings");
  return { ok: check !== "no_credits", message: CHECK_MESSAGES[check] };
}

export async function recheckOpenAIKey(_prev: FormState): Promise<FormState> {
  void _prev;
  const { tenantId, ok } = await keyAdmin();
  if (!ok || !tenantId) return { ok: false, message: "Only an owner or admin can check the OpenAI key." };
  const db = adminClient();
  const { data } = await db.from("tenant_api_keys").select("secret_enc").eq("tenant_id", tenantId).eq("provider", "openai").maybeSingle();
  if (!data) return { ok: false, message: "No key is saved." };
  const check = await checkOpenAIKey(decryptSecret(data.secret_enc));
  if (check !== "unreachable") {
    await db.from("tenant_api_keys").update({ status: check, checked_at: new Date().toISOString() }).eq("tenant_id", tenantId).eq("provider", "openai");
  }
  revalidatePath("/settings");
  const msg: Record<KeyCheck, string> = {
    ok: "The key works.", no_credits: "Still no credits on this OpenAI account. The free model is being used.",
    invalid: "OpenAI no longer accepts this key. Save a new one.", unchecked: "", unreachable: "OpenAI could not be reached. Try again in a moment.",
  };
  return { ok: check === "ok", message: msg[check] };
}

export async function removeOpenAIKey(_prev: FormState): Promise<FormState> {
  void _prev;
  const { tenantId, ok } = await keyAdmin();
  if (!ok || !tenantId) return { ok: false, message: "Only an owner or admin can remove the OpenAI key." };
  const { error } = await adminClient().from("tenant_api_keys").delete().eq("tenant_id", tenantId).eq("provider", "openai");
  if (error) return { ok: false, message: "Could not remove. " + error.message };
  revalidatePath("/settings");
  return { ok: true, message: "Removed. Your agents now use the free model." };
}
