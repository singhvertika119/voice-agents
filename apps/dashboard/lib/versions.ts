import type { SupabaseClient } from "@supabase/supabase-js";
import type { AgentConfig } from "@/lib/agent-config";
import { dbMessage } from "@/lib/action-state";

// Agent versions, shared by the agent builder and the setup wizard. Every call runs as the signed-in user, so
// row-level security decides what they may read and change.

export type VersionRow = { version: number; status: string; config: AgentConfig };

export async function latestVersion(supabase: SupabaseClient, agentId: string): Promise<VersionRow | null> {
  const { data } = await supabase.from("agent_versions").select("version,status,config").eq("agent_id", agentId)
    .order("version", { ascending: false }).limit(1).maybeSingle();
  return data as VersionRow | null;
}

// Prefers the active draft if one exists, else the currently published version (even if newer versions were archived
// after 'Make live again'), else the highest version.
export async function activeOrLatestVersion(supabase: SupabaseClient, agentId: string): Promise<VersionRow | null> {
  const { data: draft } = await supabase.from("agent_versions").select("version,status,config")
    .eq("agent_id", agentId).eq("status", "draft").order("version", { ascending: false }).limit(1).maybeSingle();
  if (draft) return draft as VersionRow;

  const { data: agent } = await supabase.from("agents").select("published_version").eq("id", agentId).maybeSingle();
  if (agent?.published_version) {
    const { data: pub } = await supabase.from("agent_versions").select("version,status,config")
      .eq("agent_id", agentId).eq("version", agent.published_version).maybeSingle();
    if (pub) return pub as VersionRow;
  }

  return latestVersion(supabase, agentId);
}

// A new agent with its first draft. Returns the agent id, or a message to show.
export async function createAgent(supabase: SupabaseClient, tenantId: string, name: string, config: AgentConfig | Record<string, unknown>, note: string): Promise<{ id: string } | { error: string }> {
  const { data: agent, error } = await supabase.from("agents").insert({ tenant_id: tenantId, name }).select("id").single();
  if (error || !agent) return { error: dbMessage(error, "Could not create the agent.") };
  const { error: dErr } = await supabase.rpc("create_draft", { p_agent: agent.id, p_config: config, p_note: note });
  if (dErr) {
    await supabase.from("agents").delete().eq("id", agent.id);   // no half-made agent without a version
    return { error: dbMessage(dErr, "Could not create the agent.") };
  }
  return { id: agent.id as string };
}

// Drafts are edited in place; a published version is never edited, so saving it creates a new draft instead.
// Returns the version the config now lives in, or a message to show.
export async function saveConfig(supabase: SupabaseClient, agentId: string, latest: VersionRow, config: AgentConfig, note: string): Promise<{ version: number } | { error: string }> {
  if (latest.status === "draft") {
    const { data, error } = await supabase.from("agent_versions").update({ config }).eq("agent_id", agentId).eq("version", latest.version).eq("status", "draft").select("version");
    if (error) return { error: dbMessage(error, "You may not have permission to edit this agent.") };
    if (data?.length) return { version: latest.version };
    // Someone published this version concurrently; fall through to create a new draft.
  }
  const { data, error } = await supabase.rpc("create_draft", { p_agent: agentId, p_config: config, p_note: note });
  if (error) return { error: dbMessage(error) };
  return { version: data as number };
}

// Make a version live. null when it worked, otherwise a message to show; testsRequired is the message for a workspace
// that requires passing test conversations first.
export async function publishVersion(supabase: SupabaseClient, agentId: string, version: number, override: boolean, testsRequired: string): Promise<string | null> {
  const { error } = await supabase.rpc("publish_version", { p_agent: agentId, p_version: version, p_override: override });
  if (!error) return null;
  return error.message.startsWith("tests_required") ? testsRequired : dbMessage(error, "Could not publish. Please try again.");
}
