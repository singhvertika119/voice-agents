"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";

export type ScenarioState = { ok: boolean; message: string; at: number } | null;

export async function queueTests(agentId: string, version: number) {
  const supabase = await supabaseServer();
  const { data: agent } = await supabase.from("agents").select("tenant_id").eq("id", agentId).single();
  if (!agent) redirect(`/agents/${agentId}?tab=tests&error=${encodeURIComponent("Agent not found.")}`);
  const { error } = await supabase.from("eval_runs").insert({ tenant_id: agent.tenant_id, agent_id: agentId, agent_version: version, status: "queued", runs_per_scenario: 3 });
  if (error) redirect(`/agents/${agentId}?tab=tests&error=${encodeURIComponent(error.message.includes("eval_runs") ? "Tests are not available yet: the database update has not been applied." : error.message)}`);
  revalidatePath(`/agents/${agentId}`);
  redirect(`/agents/${agentId}?tab=tests`);
}

export async function addScenario(agentId: string, _prev: ScenarioState, formData: FormData): Promise<ScenarioState> {
  const supabase = await supabaseServer();
  const { data: agent } = await supabase.from("agents").select("tenant_id").eq("id", agentId).single();
  if (!agent) return { ok: false, message: "Agent not found.", at: Date.now() };
  const says = String(formData.get("caller_says") ?? "").trim();
  if (says.length < 5) return { ok: false, message: "Write what the caller says, for example: Admission fees kitni hai?", at: Date.now() };
  const list = (k: string) => String(formData.get(k) ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  const name = String(formData.get("name") ?? "").trim() || says.slice(0, 40);
  const { error } = await supabase.from("eval_scenarios").insert({
    tenant_id: agent.tenant_id, agent_id: agentId, name,
    spec: { caller_says: says, must_say_any: list("must_say"), must_not_say: list("must_not_say") },
  });
  if (error) return { ok: false, message: "Could not save the test. " + error.message, at: Date.now() };
  revalidatePath(`/agents/${agentId}`);
  return { ok: true, message: "Test added. It runs with the next test run.", at: Date.now() };
}

export async function deleteScenario(agentId: string, id: string) {
  const supabase = await supabaseServer();
  await supabase.from("eval_scenarios").delete().eq("id", id);
  revalidatePath(`/agents/${agentId}`);
}

export async function setAgentEnabled(agentId: string, enabled: boolean) {
  const supabase = await supabaseServer();
  await supabase.from("agents").update({ enabled }).eq("id", agentId);
  revalidatePath(`/agents/${agentId}`);
}
