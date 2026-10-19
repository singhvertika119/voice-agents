import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Card } from "@/components/ui";
import { TestPanel } from "@/components/test-panel";
import { WizardFooter } from "@/components/wizard";
import { BUSINESS_TYPES } from "@/lib/templates";
import { findPlaceholders, type AgentConfig } from "@/lib/agent-config";
import { goLive } from "../actions";

export default async function TestCallStep({ searchParams }: { searchParams: Promise<{ agent?: string; error?: string }> }) {
  const { agent, error } = await searchParams;
  if (!agent) redirect("/onboarding/business-type");
  const supabase = await supabaseServer();
  const { data: a } = await supabase.from("agents").select("id,name,published_version").eq("id", agent).single();
  const { data: v } = await supabase.from("agent_versions").select("config,status").eq("agent_id", agent).order("version", { ascending: false }).limit(1).single();
  if (!a || !v) redirect("/onboarding/business-type");
  const cfg = v.config as AgentConfig;
  const type = BUSINESS_TYPES.find((t) => t.id === cfg.wizard?.type) ?? BUSINESS_TYPES[BUSINESS_TYPES.length - 1];
  return (
    <div className="flex flex-col gap-7 flex-1">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">Try it before you go live</h1>
        <p className="text-[15px] text-ink-muted mt-2">Press the button and talk to {a.name} from your browser. Allow the microphone when asked.</p>
      </div>
      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[1_1_340px] min-w-0">
          <TestPanel agentId={agent} hasLive={!!a.published_version} hasDraft={v.status === "draft"} placeholders={findPlaceholders(cfg)} />
        </div>
        <aside className="flex-[1_1_300px] min-w-0">
          <Card className="p-5 flex flex-col gap-3">
            <h2 className="text-base font-semibold">Try these on the call</h2>
            <ul className="flex flex-col gap-2.5 text-sm leading-snug list-none">
              {[...type.tryThese, "Mujhe kisi insaan se baat karni hai"].map((t) => (
                <li key={t} className="flex items-start gap-3"><span className="mt-1.5 size-1.5 rounded-full bg-ink-faint shrink-0" aria-hidden />{t}</li>
              ))}
            </ul>
            <p className="text-[13px] text-ink-muted">If it says it does not have an answer, add that to your knowledge. That is how the agent stays honest.</p>
          </Card>
        </aside>
      </div>
      {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}
      <form action={goLive.bind(null, agent)} className="mt-auto flex flex-col gap-3">
        <p className="text-[13px] text-ink-muted">Going live makes this the version new calls use. Phone numbers are connected separately; until then you can keep testing from the browser.</p>
        <WizardFooter backHref={`/onboarding/voice?agent=${agent}`} primary="Publish and go live" />
      </form>
    </div>
  );
}
