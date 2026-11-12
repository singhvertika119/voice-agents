"use server";

import { revalidatePath } from "next/cache";
import { dbMessage, done, fail, type ActionState } from "@/lib/action-state";
import { currentMember, isAdmin } from "@/lib/membership";
import { checkOpenAIKey, type KeyCheck } from "@/lib/openai-key";
import { indianMobile, toE164 } from "@/lib/phone";
import { decryptSecret, encryptSecret } from "@/lib/server-security";
import { adminClient } from "@/lib/supabase/admin";

const num = (v: FormDataEntryValue | null, min: number, max: number, fallback: number) => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : fallback;
};

export async function saveSettings(_prev: ActionState, formData: FormData): Promise<ActionState> {
  const { supabase, tenantId, role } = await currentMember();
  if (!tenantId || !isAdmin(role)) return fail("Only an owner or admin can change settings.");
  const days = formData.getAll("days").map(Number).filter((d) => d >= 1 && d <= 7).sort();
  const start = String(formData.get("start") ?? "09:00");
  const end = String(formData.get("end") ?? "19:00");
  if (!/^\d\d:\d\d$/.test(start) || !/^\d\d:\d\d$/.test(end) || start >= end) return fail("Closing time must be after opening time.");
  if (!days.length) return fail("Choose at least one working day.");
  const rawPhone = String(formData.get("handoff_phone") ?? "").trim();
  const phone = rawPhone ? indianMobile(rawPhone) : null;
  if (rawPhone && !phone) return fail("Enter a 10-digit mobile number for your team, or leave it empty.");
  const { error } = await supabase.from("tenant_settings").upsert({
    tenant_id: tenantId,
    business_hours: { days, start, end },
    handoff_phone: phone,
    retention_days: num(formData.get("retention_days"), 1, 3650, 90),
    max_concurrent_calls: num(formData.get("max_concurrent_calls"), 1, 500, 5),
    memory_enabled: formData.get("memory_enabled") === "on",
    record_calls: formData.get("record_calls") === "on",
    require_tests_to_publish: formData.get("require_tests") === "on",
    updated_at: new Date().toISOString(),
  });
  if (error) return fail("Could not save. " + dbMessage(error));
  revalidatePath("/settings");
  return done("Saved.");
}

// "Delete everything about this caller". Runs inside the database so every related record goes in one step.
export async function eraseCaller(_prev: ActionState, formData: FormData): Promise<ActionState> {
  const { supabase, tenantId, role } = await currentMember();
  if (!tenantId || !isAdmin(role)) return fail("Only an owner or admin can erase a caller's data.");
  if (formData.get("confirm") !== "on") return fail("Tick the box to confirm. This cannot be undone.");
  const phone = toE164(String(formData.get("phone") ?? ""));
  if (!phone) return fail("Enter the caller's 10-digit mobile number, or the full number starting with + for a number outside India.");
  // Audio files are not in the database, so remove them first (the erase function below cannot reach storage).
  const { data: rec } = await supabase.from("calls").select("recording_path").eq("tenant_id", tenantId).eq("caller_number", phone).not("recording_path", "is", null);
  const paths = (rec ?? []).map((r) => r.recording_path as string);
  if (paths.length) {
    const { error: rmErr } = await adminClient().storage.from("recordings").remove(paths);
    if (rmErr) return fail("Could not delete the recordings, so nothing was erased. Try again.");
  }
  const { data, error } = await supabase.rpc("erase_caller", { p_tenant: tenantId, p_phone: phone });
  if (error) return fail("Could not erase. " + dbMessage(error));
  const r = data as { calls: number; contacts: number; callbacks: number };
  revalidatePath("/calls");
  return done(`Erased ${r.calls} call${r.calls === 1 ? "" : "s"} with transcripts and ${paths.length} recording${paths.length === 1 ? "" : "s"}, ${r.contacts} saved profile${r.contacts === 1 ? "" : "s"} and ${r.callbacks} callback request${r.callbacks === 1 ? "" : "s"}.`);
}

// ---------------------------------------------------------------- the workspace's own OpenAI key (D-124)
// The key is checked with OpenAI, encrypted here and stored where only server code can read it. It is never shown
// again: Settings shows only its last four characters and whether it works.
const SAVE_MESSAGES: Record<KeyCheck, string> = {
  ok: "Saved. The key works.",
  no_credits: "Saved, but this OpenAI account has no credits left, so the free model is used until you add credits.",
  invalid: "OpenAI did not accept this key. Check that you copied all of it.",
  unchecked: "Saved.",
  unreachable: "Saved, but OpenAI could not be reached to check it. It will be checked on first use.",
};
const RECHECK_MESSAGES: Record<Exclude<KeyCheck, "unchecked">, string> = {
  ok: "The key works.",
  no_credits: "Still no credits on this OpenAI account. The free model is being used.",
  invalid: "OpenAI no longer accepts this key. Save a new one.",
  unreachable: "OpenAI could not be reached. Try again in a moment.",
};

async function keyAdmin() {
  const { tenantId, role } = await currentMember();
  return tenantId && isAdmin(role) ? tenantId : null;
}

export async function saveOpenAIKey(_prev: ActionState, formData: FormData): Promise<ActionState> {
  const { supabase, tenantId, role } = await currentMember();
  if (!tenantId || !isAdmin(role)) return fail("Only an owner or admin can change the OpenAI key.");
  const key = String(formData.get("openai_key") ?? "").trim();
  if (!/^sk-[A-Za-z0-9_-]{20,}$/.test(key)) return fail("That does not look like an OpenAI key. It starts with sk- and is long.");
  const check = await checkOpenAIKey(key);
  if (check === "invalid") return fail(SAVE_MESSAGES.invalid);
  const { data: user } = await supabase.auth.getUser();
  const { error } = await adminClient().from("tenant_api_keys").upsert({
    tenant_id: tenantId, provider: "openai", secret_enc: encryptSecret(key), last4: key.slice(-4),
    status: check === "unreachable" ? "unchecked" : check,
    checked_at: check === "unreachable" ? null : new Date().toISOString(),
    updated_at: new Date().toISOString(), updated_by: user.user?.id ?? null,
  });
  if (error) return fail("Could not save. " + dbMessage(error));
  revalidatePath("/settings");
  return { ok: check !== "no_credits", message: SAVE_MESSAGES[check] };
}

export async function recheckOpenAIKey(): Promise<ActionState> {
  const tenantId = await keyAdmin();
  if (!tenantId) return fail("Only an owner or admin can check the OpenAI key.");
  const db = adminClient();
  const { data } = await db.from("tenant_api_keys").select("secret_enc").eq("tenant_id", tenantId).eq("provider", "openai").maybeSingle();
  if (!data) return fail("No key is saved.");
  let key: string;
  try {
    key = decryptSecret(data.secret_enc);
  } catch {
    return fail("The saved key could not be read (the server's encryption key changed). Save the key again.");
  }
  const check = await checkOpenAIKey(key);
  if (check === "unchecked") return fail(RECHECK_MESSAGES.unreachable);   // checkOpenAIKey never returns it; for the type
  if (check !== "unreachable") {
    await db.from("tenant_api_keys").update({ status: check, checked_at: new Date().toISOString() }).eq("tenant_id", tenantId).eq("provider", "openai");
  }
  revalidatePath("/settings");
  return { ok: check === "ok", message: RECHECK_MESSAGES[check] };
}

// What the key is used for (D-125): "calls" keeps OpenAI for live calls only, the cheapest choice.
export async function saveKeyUse(_prev: ActionState, formData: FormData): Promise<ActionState> {
  const tenantId = await keyAdmin();
  if (!tenantId) return fail("Only an owner or admin can change this.");
  const useFor = String(formData.get("use_for"));
  if (!["calls", "everything"].includes(useFor)) return fail("Pick one of the two options.");
  const { error } = await adminClient().from("tenant_api_keys").update({ use_for: useFor, updated_at: new Date().toISOString() })
    .eq("tenant_id", tenantId).eq("provider", "openai");
  if (error) return fail("Could not save. " + dbMessage(error));
  revalidatePath("/settings");
  return done(useFor === "calls" ? "Saved. OpenAI is used for calls only." : "Saved. OpenAI is used for everything.");
}

export async function removeOpenAIKey(): Promise<ActionState> {
  const tenantId = await keyAdmin();
  if (!tenantId) return fail("Only an owner or admin can remove the OpenAI key.");
  const { error } = await adminClient().from("tenant_api_keys").delete().eq("tenant_id", tenantId).eq("provider", "openai");
  if (error) return fail("Could not remove. " + dbMessage(error));
  revalidatePath("/settings");
  return done("Removed. Your agents now use the free model.");
}
