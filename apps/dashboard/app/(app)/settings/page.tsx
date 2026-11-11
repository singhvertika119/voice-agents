import { supabaseServer } from "@/lib/supabase/server";
import { PageHeader } from "@/components/ui";
import { EraseForm, OpenAIKeyForm, SettingsForm, type OpenAIKeyInfo, type SettingsValues } from "@/components/settings-forms";
import { adminClient } from "@/lib/openai-key";

export default async function SettingsPage() {
  const supabase = await supabaseServer();
  const { data: member } = await supabase.from("tenant_members").select("tenant_id,role").limit(1).single();
  const { data: s, error } = await supabase.from("tenant_settings").select("*").maybeSingle();
  const h = (s?.business_hours ?? { days: [1, 2, 3, 4, 5, 6], start: "09:00", end: "19:00" }) as { days: number[]; start: string; end: string };
  const v: SettingsValues = {
    days: h.days, start: h.start, end: h.end,
    handoff_phone: (s?.handoff_phone ?? "").replace("+91", ""),
    retention_days: s?.retention_days ?? 90,
    max_concurrent_calls: s?.max_concurrent_calls ?? 5,
    memory_enabled: s?.memory_enabled ?? true,
    require_tests: s?.require_tests_to_publish ?? false,
    record_calls: s?.record_calls ?? true,
  };
  const canEdit = ["owner", "admin"].includes(member?.role ?? "");
  // Only the last 4 characters and the status: the key itself stays on the server (D-124).
  let keyInfo: OpenAIKeyInfo = null;
  if (member?.tenant_id) {
    const { data: k } = await adminClient().from("tenant_api_keys").select("*")
      .eq("tenant_id", member.tenant_id).eq("provider", "openai").maybeSingle();
    keyInfo = k ? { last4: k.last4, status: k.status, checked_at: k.checked_at, use_for: k.use_for ?? "calls" } : null;
  }
  return (
    <>
      <PageHeader title="Settings" intro="Hours, limits and privacy for your workspace." />
      {error && <p role="alert" className="text-[13px] text-danger-fg">Settings are not available yet: the database update for them has not been applied.</p>}
      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[999_1_480px] min-w-0"><SettingsForm v={v} canEdit={canEdit} /></div>
        <aside className="flex-[1_1_320px] min-w-0 flex flex-col gap-6"><OpenAIKeyForm info={keyInfo} canEdit={canEdit} /><EraseForm canEdit={canEdit} /></aside>
      </div>
    </>
  );
}
