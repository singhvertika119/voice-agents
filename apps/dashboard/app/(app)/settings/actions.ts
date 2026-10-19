"use server";

import { revalidatePath } from "next/cache";
import { supabaseServer } from "@/lib/supabase/server";

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
    require_tests_to_publish: formData.get("require_tests") === "on",
    updated_at: new Date().toISOString(),
  };
  const { error } = await supabase.from("tenant_settings").upsert(row);
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
  const digits = String(formData.get("phone") ?? "").replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "").replace(/^0/, "");
  if (!/^[6-9]\d{9}$/.test(digits)) return { ok: false, message: "Enter the caller's 10-digit mobile number." };
  const { data, error } = await supabase.rpc("erase_caller", { p_tenant: tenantId, p_phone: `+91${digits}` });
  if (error) return { ok: false, message: "Could not erase. " + error.message };
  const r = data as { calls: number; contacts: number; callbacks: number };
  revalidatePath("/calls");
  return {
    ok: true,
    message: `Erased ${r.calls} call${r.calls === 1 ? "" : "s"} with transcripts, ${r.contacts} saved profile${r.contacts === 1 ? "" : "s"} and ${r.callbacks} callback request${r.callbacks === 1 ? "" : "s"}.`,
  };
}
