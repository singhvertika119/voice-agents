import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Card, Field, inputCls, textareaCls } from "@/components/ui";
import { PlayButton, WizardFooter } from "@/components/wizard";
import { BUSINESS_TYPES, LANGUAGES, buildGreeting } from "@/lib/templates";
import type { AgentConfig } from "@/lib/agent-config";
import { saveDetails } from "../actions";

export default async function DetailsStep({ searchParams }: { searchParams: Promise<{ agent?: string; error?: string }> }) {
  const { agent, error } = await searchParams;
  if (!agent) redirect("/onboarding/business-type");
  const supabase = await supabaseServer();
  const { data: v } = await supabase.from("agent_versions").select("config").eq("agent_id", agent).order("version", { ascending: false }).limit(1).single();
  if (!v) redirect("/onboarding/business-type");
  const cfg = v.config as AgentConfig;
  const type = BUSINESS_TYPES.find((t) => t.id === cfg.wizard?.type) ?? BUSINESS_TYPES[BUSINESS_TYPES.length - 1];
  const d = cfg.wizard?.details;
  const { data: s } = await supabase.from("tenant_settings").select("handoff_phone").maybeSingle();
  const languages = d?.languages ?? ["hinglish"];
  const greeting = buildGreeting(d?.name || "your business", languages);

  return (
    <form action={saveDetails.bind(null, agent)} className="flex flex-col gap-7 flex-1">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">Tell us about your business</h1>
        <p className="text-[15px] text-ink-muted mt-2">The agent only says what you write here and in the next step. Leave a box empty if you do not want it to answer that.</p>
      </div>
      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[999_1_420px] min-w-0 flex flex-col gap-5">
          <Field label="Business name"><input name="name" required defaultValue={d?.name ?? ""} className={inputCls} placeholder="Sunrise Clinic" /></Field>
          <Field label="Address (optional)" helper="Callers ask where you are. Write it the way you would say it aloud.">
            <input name="address" defaultValue={d?.address ?? ""} className={inputCls} placeholder="Sector 62, Noida" />
          </Field>
          <Field label="Timings (optional)" helper="For example: Monday to Saturday, 9 am to 7 pm. Sunday closed.">
            <input name="hours" defaultValue={d?.hours ?? ""} className={inputCls} placeholder="Monday to Saturday, 9 am to 7 pm. Sunday closed." />
          </Field>
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium mb-1">Languages your callers speak</legend>
            <div className="flex flex-wrap gap-2">
              {LANGUAGES.map((l) => (
                <label key={l.id} className="min-h-10 px-3.5 inline-flex items-center gap-2 rounded-full border text-sm border-line-strong text-ink-muted has-[:checked]:border-ink has-[:checked]:bg-muted has-[:checked]:text-ink">
                  <input type="checkbox" name="languages" value={l.id} defaultChecked={languages.includes(l.id)} className="accent-ink" /> {l.label}
                </label>
              ))}
              <span className="min-h-10 px-3.5 inline-flex items-center rounded-full border border-line text-sm text-ink-faint">Other Indian languages (soon)</span>
            </div>
          </fieldset>
          <Field label="Top reasons people call you" helper="One line. The agent uses it to know what matters.">
            <textarea name="reasons" rows={3} defaultValue={d?.reasons ?? ""} className={textareaCls} placeholder={type.reasonsExample} />
          </Field>
          <Field label="Number for your team (optional)" helper="Where handoffs will ring once phone lines are connected. Until then the agent books a callback.">
            <div className="flex gap-2">
              <span className="h-11 px-3 inline-flex items-center rounded-md border border-line-strong bg-muted font-mono text-sm">+91</span>
              <input name="handoff_phone" inputMode="numeric" defaultValue={(s?.handoff_phone ?? "").replace("+91", "")} className={`${inputCls} font-mono text-sm max-w-60`} placeholder="98765 43210" />
            </div>
          </Field>
        </div>
        <aside className="flex-[1_1_300px] min-w-0">
          <Card className="p-5 flex flex-col gap-3">
            <span className="text-xs font-medium uppercase tracking-[0.04em] text-ink-muted">Callers will hear</span>
            <p className="text-[15px] leading-normal">{greeting}</p>
            <p className="text-[13px] text-ink-muted">The line about it being an AI assistant and the call being recorded is always included. It is shown with your name after you continue.</p>
            <PlayButton voice="ritu" text={greeting} label="Play greeting" />
          </Card>
        </aside>
      </div>
      {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}
      <WizardFooter backHref="/onboarding/business-type" primary="Continue" />
    </form>
  );
}
