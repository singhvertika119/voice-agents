"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { dbMessage, done, fail, type ActionState } from "@/lib/action-state";
import { DEFAULT_CONFIG, VOICES, findPlaceholders, type AgentConfig } from "@/lib/agent-config";
import { currentMember } from "@/lib/membership";
import { supabaseServer } from "@/lib/supabase/server";
import { createAgent as create, latestVersion, publishVersion, saveConfig } from "@/lib/versions";

export async function createAgent(formData: FormData) {
  const name = String(formData.get("name") ?? "").trim() || "New agent";
  const { supabase, tenantId } = await currentMember();
  if (!tenantId) redirect("/login");
  const made = await create(supabase, tenantId, name, DEFAULT_CONFIG, "First draft");
  if ("error" in made) redirect(`/agents?error=${encodeURIComponent(made.error)}`);
  redirect(`/agents/${made.id}`);
}

// Saves the editor form into the latest draft (or a new draft, if the latest version is published).
export async function saveDraft(agentId: string, _prev: ActionState, formData: FormData): Promise<ActionState> {
  const supabase = await supabaseServer();
  const latest = await latestVersion(supabase, agentId);
  if (!latest) return fail("Could not load the agent. Refresh the page and try again.");

  const next: AgentConfig = structuredClone(latest.config);
  for (const key of ["greeting", "instructions", "knowledge"] as const) {
    const v = formData.get(key);
    if (typeof v === "string") next[key] = v;
  }
  // The name belongs to the agent, not to a version, so it changes at once and does not create a draft.
  const rawName = formData.get("name");
  if (typeof rawName === "string") {
    const newName = rawName.trim();
    if (!newName) return fail("The agent needs a name.");
    if (newName.length > 60) return fail("Keep the name under 60 characters.");
    const { error: nameErr } = await supabase.from("agents").update({ name: newName }).eq("id", agentId);
    if (nameErr) return fail(`The name was not saved. ${dbMessage(nameErr)}`);
  }
  const voice = formData.get("voice");
  if (typeof voice === "string" && VOICES.some((x) => x.id === voice)) {
    next.voice.tts_primary = { ...next.voice.tts_primary, speaker: voice };
  }
  if (formData.get("sources_present") === "1") {
    const asked = formData.getAll("source").map(String);
    // Row-level security hides other workspaces' sources, so forged ids are dropped here.
    const { data: mine } = asked.length ? await supabase.from("knowledge_sources").select("id").in("id", asked).eq("status", "ready") : { data: [] };
    next.knowledge_sources = (mine ?? []).map((r) => r.id as string);
  }
  if (formData.get("tools_present") === "1") {
    const asked = formData.getAll("tool").map(String);
    const { data: mineTools } = asked.length ? await supabase.from("tools").select("id").in("id", asked).eq("enabled", true) : { data: [] };
    next.tool_ids = (mineTools ?? []).map((r) => r.id as string);
  }

  const saved = await saveConfig(supabase, agentId, latest, next, "Edited");
  if ("error" in saved) return fail(`Your changes were not saved. ${saved.error}`);
  revalidatePath(`/agents/${agentId}`);
  revalidatePath("/agents");
  const left = findPlaceholders(next);
  return done(left.length
    ? `Saved as draft v${saved.version}. Replace ${left.slice(0, 3).join(", ")}${left.length > 3 ? " and more" : ""} before publishing.`
    : `Saved as draft v${saved.version}.`);
}

// Removes the agent with its versions, test runs and caller memory. Its calls stay, shown as "Deleted agent".
export async function deleteAgent(agentId: string) {
  const supabase = await supabaseServer();
  const { data, error } = await supabase.from("agents").delete().eq("id", agentId).select("id");
  if (error) redirect(`/agents/${agentId}?error=${encodeURIComponent(`The agent was not deleted. ${dbMessage(error)}`)}`);
  if (!data?.length) redirect(`/agents/${agentId}?error=${encodeURIComponent("The agent was not deleted. You may not have permission, or it is already gone.")}`);
  revalidatePath("/agents");
  redirect("/agents?deleted=1");
}

export async function publish(agentId: string, version: number, override = false) {
  const supabase = await supabaseServer();
  const { data: v } = await supabase.from("agent_versions").select("config").eq("agent_id", agentId).eq("version", version).single();
  const left = v ? findPlaceholders(v.config as AgentConfig) : [];
  if (left.length) {
    redirect(`/agents/${agentId}?tab=versions&error=${encodeURIComponent(`Replace the placeholders first: ${left.join(", ")}. The agent would say them out loud.`)}`);
  }
  const err = await publishVersion(supabase, agentId, version, override,
    "Run the test conversations for this version and pass them first (Tests tab). An owner or admin can use Publish anyway.");
  if (err) redirect(`/agents/${agentId}?tab=versions&error=${encodeURIComponent(err)}`);
  revalidatePath(`/agents/${agentId}`);
  redirect(`/agents/${agentId}?tab=versions`);
}
