"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { VOICES, findPlaceholders, type AgentConfig } from "@/lib/agent-config";
import { currentMember } from "@/lib/membership";
import { indianMobile } from "@/lib/phone";
import { supabaseServer } from "@/lib/supabase/server";
import { BUSINESS_TYPES, LANGUAGES, businessType, buildGreeting, buildInstructions, buildNotes, templateConfig, type Details } from "@/lib/templates";
import { createAgent, latestVersion, publishVersion, saveConfig } from "@/lib/versions";

const next = (step: string, agent: string) => `/onboarding/${step}?agent=${agent}`;
const back = (step: string, agent: string, error: string) => `/onboarding/${step}?agent=${agent}&error=${encodeURIComponent(error)}`;

// Change the agent's latest config and save it. Returns a message to show, or null when it worked.
async function updateConfig(agentId: string, mutate: (c: AgentConfig) => void): Promise<string | null> {
  const supabase = await supabaseServer();
  const latest = await latestVersion(supabase, agentId);
  if (!latest) return "Could not load your agent. Start again from the first step.";
  const config = structuredClone(latest.config);
  mutate(config);
  const saved = await saveConfig(supabase, agentId, latest, config, "Setup wizard");
  return "error" in saved ? "Your answers were not saved. " + saved.error : null;
}

// Step 1: create the agent from a template.
export async function startFromTemplate(formData: FormData) {
  const type = BUSINESS_TYPES.find((t) => t.id === formData.get("type"));
  if (!type) redirect("/onboarding/business-type?error=" + encodeURIComponent("Choose the kind of business first."));
  const { supabase, tenantId } = await currentMember();
  if (!tenantId) redirect("/login");
  const made = await createAgent(supabase, tenantId, "My agent", { ...templateConfig(type), wizard: { type: type.id } }, "Setup wizard");
  if ("error" in made) redirect("/onboarding/business-type?error=" + encodeURIComponent("Could not create your agent. " + made.error));
  redirect(next("details", made.id));
}

// Step 2: business details become the greeting, the instructions and the notes the agent answers from.
export async function saveDetails(agentId: string, formData: FormData) {
  const name = String(formData.get("name") ?? "").trim();
  const details: Details = {
    name,
    address: String(formData.get("address") ?? "").trim(),
    hours: String(formData.get("hours") ?? "").trim(),
    reasons: String(formData.get("reasons") ?? "").trim(),
    languages: LANGUAGES.map((l) => l.id).filter((id) => formData.getAll("languages").includes(id)),
  };
  if (name.length < 2) redirect(back("details", agentId, "Enter your business name."));
  if (!details.languages.length) redirect(back("details", agentId, "Choose at least one language callers speak."));
  if (/[[\]]/.test(name + details.address + details.hours + details.reasons)) redirect(back("details", agentId, "Please remove square brackets [ ] from your answers; the agent would read them out loud."));
  const rawPhone = String(formData.get("handoff_phone") ?? "").trim();
  const phone = rawPhone ? indianMobile(rawPhone) : null;
  if (rawPhone && !phone) redirect(back("details", agentId, "Enter a 10-digit mobile number for your team, or leave it empty."));

  const err = await updateConfig(agentId, (c) => {
    const type = businessType(c.wizard?.type);
    c.greeting = buildGreeting(name, details.languages);
    c.instructions = buildInstructions(type, details);
    c.knowledge = buildNotes(details);
    c.language = details.languages.length === 1 && details.languages[0] === "english" ? "en-IN" : "hi-IN";
    c.wizard = { type: type.id, details };
  });
  if (err) redirect(back("details", agentId, err));
  const { supabase, tenantId } = await currentMember();
  await supabase.from("agents").update({ name, updated_at: new Date().toISOString() }).eq("id", agentId);
  if (phone && tenantId) {
    await supabase.from("tenant_settings").upsert({ tenant_id: tenantId, handoff_phone: phone, updated_at: new Date().toISOString() });
  }
  redirect(next("knowledge", agentId));
}

// Step 3: attach everything that finished reading.
export async function finishKnowledge(agentId: string) {
  const supabase = await supabaseServer();
  const { data: ready } = await supabase.from("knowledge_sources").select("id").eq("status", "ready");
  const err = await updateConfig(agentId, (c) => {
    c.knowledge_sources = (ready ?? []).map((r) => r.id as string);
  });
  if (err) redirect(back("knowledge", agentId, err));
  redirect(next("voice", agentId));
}

// Step 4
export async function saveVoice(agentId: string, formData: FormData) {
  const voice = String(formData.get("voice") ?? "");
  if (!VOICES.some((v) => v.id === voice)) redirect(back("voice", agentId, "Choose a voice."));
  const err = await updateConfig(agentId, (c) => {
    c.voice.tts_primary = { ...c.voice.tts_primary, speaker: voice };
  });
  if (err) redirect(back("voice", agentId, err));
  redirect(next("test-call", agentId));
}

// Step 5: publish. Placeholders block it, exactly as in the agent builder.
export async function goLive(agentId: string) {
  const supabase = await supabaseServer();
  const v = await latestVersion(supabase, agentId);
  if (!v) redirect(back("test-call", agentId, "Could not load your agent."));
  if (!v.config.wizard?.details) redirect(back("test-call", agentId, "Fill in the business details first (step 2)."));
  const left = findPlaceholders(v.config);
  if (left.length) redirect(back("test-call", agentId, `Replace ${left.join(", ")} first. The agent would say it out loud.`));
  const err = await publishVersion(supabase, agentId, v.version, false,
    "This workspace requires passing the test conversations before publishing. Open the agent's Tests tab.");
  if (err) redirect(back("test-call", agentId, err));
  revalidatePath("/agents");
  redirect(`/agents/${agentId}?tab=versions&live=1`);
}

// "Play greeting" and voice samples: one short synthesis with the platform's own key. Signed-in users only.
export async function previewVoice(voice: string, text: string): Promise<{ audio: string } | { error: string }> {
  const supabase = await supabaseServer();
  const { data: u } = await supabase.auth.getUser();
  if (!u.user) return { error: "Please sign in again." };
  if (!VOICES.some((v) => v.id === voice)) return { error: "Unknown voice." };
  const clean = text.replace(/\s+/g, " ").trim().slice(0, 220);
  if (clean.length < 2) return { error: "Type a sentence first." };
  try {
    const r = await fetch("https://api.sarvam.ai/text-to-speech", {
      method: "POST",
      headers: { "api-subscription-key": process.env.SARVAM_API_KEY ?? "", "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean, target_language_code: "hi-IN", speaker: voice, model: "bulbul:v3" }),
      signal: AbortSignal.timeout(15000),
    });
    if (!r.ok) return { error: r.status === 402 ? "Voice previews are paused: the voice service has no credit left." : "The voice sample is not available right now." };
    const j = await r.json();
    return { audio: `data:audio/wav;base64,${j.audios[0]}` };
  } catch {
    return { error: "The voice sample is not available right now." };
  }
}
