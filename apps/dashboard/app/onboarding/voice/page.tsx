import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { VoiceStep, WizardFooter } from "@/components/wizard";
import type { AgentConfig } from "@/lib/agent-config";
import { saveVoice } from "../actions";

export default async function VoiceStepPage({ searchParams }: { searchParams: Promise<{ agent?: string; error?: string }> }) {
  const { agent, error } = await searchParams;
  if (!agent) redirect("/onboarding/business-type");
  const supabase = await supabaseServer();
  const { data: v } = await supabase.from("agent_versions").select("config").eq("agent_id", agent).order("version", { ascending: false }).limit(1).single();
  if (!v) redirect("/onboarding/business-type");
  const cfg = v.config as AgentConfig;
  return (
    <form action={saveVoice.bind(null, agent)} className="flex flex-col gap-7 flex-1">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">Choose a voice</h1>
        <p className="text-[15px] text-ink-muted mt-2">This is the voice callers will hear. Press Hear it to listen, or type your own sentence.</p>
      </div>
      <VoiceStep initial={cfg.voice.tts_primary.speaker ?? "ritu"} />
      {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}
      <WizardFooter backHref={`/onboarding/knowledge?agent=${agent}`} primary="Continue" />
    </form>
  );
}
