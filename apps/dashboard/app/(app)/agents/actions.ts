"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { DEFAULT_CONFIG, VOICES, findPlaceholders, type AgentConfig } from "@/lib/agent-config";

export type SaveState = { ok: boolean; message: string; version?: number; at?: number } | null;

export async function createAgent(formData: FormData) {
  const name = String(formData.get("name") ?? "").trim() || "New agent";
  const supabase = await supabaseServer();
  const { data: member } = await supabase.from("tenant_members").select("tenant_id").limit(1).single();
  if (!member) redirect("/login");
  const { data: agent, error } = await supabase
    .from("agents")
    .insert({ tenant_id: member.tenant_id, name })
    .select("id")
    .single();
  if (error || !agent) redirect(`/agents?error=${encodeURIComponent(error?.message ?? "Could not create the agent")}`);
  await supabase.rpc("create_draft", { p_agent: agent.id, p_config: DEFAULT_CONFIG, p_note: "First draft" });
  redirect(`/agents/${agent.id}`);
}

// Drafts are editable in place; a published version is never edited (saving creates a new draft instead).
// Returns a message for the form instead of failing silently (an earlier version swallowed errors).
export async function saveDraft(agentId: string, _prev: SaveState, formData: FormData): Promise<SaveState> {
  const supabase = await supabaseServer();
  const { data: latest, error: readErr } = await supabase
    .from("agent_versions")
    .select("version,status,config")
    .eq("agent_id", agentId)
    .order("version", { ascending: false })
    .limit(1)
    .single();
  if (readErr || !latest) return { ok: false, message: "Could not load the agent. Refresh the page and try again." };

  const next: AgentConfig = structuredClone(latest.config as AgentConfig);
  for (const key of ["greeting", "instructions", "knowledge"] as const) {
    const v = formData.get(key);
    if (typeof v === "string") next[key] = v;
  }
  // The name belongs to the agent, not to a version, so it changes at once and does not create a draft.
  const rawName = formData.get("name");
  if (typeof rawName === "string") {
    const newName = rawName.trim();
    if (!newName) return { ok: false, message: "The agent needs a name." };
    if (newName.length > 60) return { ok: false, message: "Keep the name under 60 characters." };
    const { error: nameErr } = await supabase.from("agents").update({ name: newName }).eq("id", agentId);
    if (nameErr) return { ok: false, message: `The name was not saved. ${nameErr.message}` };
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

  let version = latest.version as number;
  if (latest.status === "draft") {
    const { data, error } = await supabase
      .from("agent_versions")
      .update({ config: next })
      .eq("agent_id", agentId)
      .eq("version", version)
      .select("version");
    if (error || !data?.length) return { ok: false, message: `Your changes were not saved. ${error?.message ?? "You may not have permission to edit this agent."}` };
  } else {
    const { data, error } = await supabase.rpc("create_draft", { p_agent: agentId, p_config: next, p_note: "Edited" });
    if (error) return { ok: false, message: `Your changes were not saved. ${error.message}` };
    version = data as number;
  }
  revalidatePath(`/agents/${agentId}`);
  revalidatePath("/agents");
  const left = findPlaceholders(next);
  return {
    ok: true,
    version,
    at: Date.now(),
    message: left.length
      ? `Saved as draft v${version}. Replace ${left.slice(0, 3).join(", ")}${left.length > 3 ? " and more" : ""} before publishing.`
      : `Saved as draft v${version}.`,
  };
}

// Removes the agent with its versions, test runs and caller memory. Its calls stay (shown as "Deleted agent") once
// migration 0007 is applied; without it the database refuses because calls still point at the agent.
export async function deleteAgent(agentId: string) {
  const supabase = await supabaseServer();
  const { data, error } = await supabase.from("agents").delete().eq("id", agentId).select("id");
  if (error) {
    const msg = error.code === "23503"
      ? "This agent has taken calls, and the database needs one small update before it can keep them (db/migrations/0007_delete_agents.sql in the SQL editor). Nothing was deleted."
      : `The agent was not deleted. ${error.message}`;
    redirect(`/agents/${agentId}?error=${encodeURIComponent(msg)}`);
  }
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
  let { error } = await supabase.rpc("publish_version", { p_agent: agentId, p_version: version, p_override: override });
  if (error && /p_override|function .*publish_version/i.test(error.message)) {
    // Database without the newest update: the old two-argument function.
    ({ error } = await supabase.rpc("publish_version", { p_agent: agentId, p_version: version }));
  }
  if (error) {
    const msg = error.message.startsWith("tests_required")
      ? "Run the test conversations for this version and pass them first (Tests tab). An owner or admin can use Publish anyway."
      : error.message;
    redirect(`/agents/${agentId}?tab=versions&error=${encodeURIComponent(msg)}`);
  }
  revalidatePath(`/agents/${agentId}`);
  redirect(`/agents/${agentId}?tab=versions`);
}
