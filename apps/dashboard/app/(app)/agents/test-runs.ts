"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { dbMessage, done, fail, type ActionState } from "@/lib/action-state";
import { canEdit, currentMember } from "@/lib/membership";
import { adminClient } from "@/lib/supabase/admin";
import { supabaseServer } from "@/lib/supabase/server";
import { STOPPED } from "@/lib/test-runs";

export async function queueTests(agentId: string, version: number) {
  const supabase = await supabaseServer();
  const { data: agent } = await supabase.from("agents").select("tenant_id").eq("id", agentId).single();
  if (!agent) redirect(`/agents/${agentId}?tab=tests&error=${encodeURIComponent("Agent not found.")}`);
  const { error } = await supabase.from("eval_runs").insert({ tenant_id: agent.tenant_id, agent_id: agentId, agent_version: version, status: "queued", runs_per_scenario: 3 });
  if (error) redirect(`/agents/${agentId}?tab=tests&error=${encodeURIComponent("Could not start the tests. " + dbMessage(error))}`);
  revalidatePath(`/agents/${agentId}`);
  redirect(`/agents/${agentId}?tab=tests`);
}

export async function addScenario(agentId: string, _prev: ActionState, formData: FormData): Promise<ActionState> {
  const supabase = await supabaseServer();
  const { data: agent } = await supabase.from("agents").select("tenant_id").eq("id", agentId).single();
  if (!agent) return fail("Agent not found.");
  const says = String(formData.get("caller_says") ?? "").trim();
  if (says.length < 5) return fail("Write what the caller says, for example: Admission fees kitni hai?");
  const list = (k: string) => String(formData.get(k) ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  const name = String(formData.get("name") ?? "").trim() || says.slice(0, 40);
  const { error } = await supabase.from("eval_scenarios").insert({
    tenant_id: agent.tenant_id, agent_id: agentId, name,
    spec: { caller_says: says, must_say_any: list("must_say"), must_not_say: list("must_not_say") },
  });
  if (error) return fail("Could not save the test. " + dbMessage(error));
  revalidatePath(`/agents/${agentId}`);
  return done("Test added. It runs with the next test run.");
}

export async function deleteScenario(agentId: string, id: string) {
  const supabase = await supabaseServer();
  await supabase.from("eval_scenarios").delete().eq("id", id);
  revalidatePath(`/agents/${agentId}`);
}

// Stops a waiting or running test run (D-109). Users may not update eval_runs directly (only the test worker writes
// results), so access is checked with the user's own session (row-level security: a member of the workspace with an
// editing role) and the change is made with the server key. The worker sees the status change and stops starting
// new conversations; the ones already talking finish within about half a minute.
export async function stopRun(agentId: string, runId: string) {
  const supabase = await supabaseServer();
  const { data: run } = await supabase.from("eval_runs").select("id,tenant_id,status").eq("id", runId).single();
  if (!run || !["queued", "running"].includes(run.status)) return;
  const { role } = await currentMember(run.tenant_id);
  if (!canEdit(role)) return;
  await adminClient().from("eval_runs").update({ status: "failed", error: STOPPED, finished_at: new Date().toISOString() })
    .eq("id", runId).in("status", ["queued", "running"]);
  revalidatePath(`/agents/${agentId}`);
}

// Removes the saved questions written from the agent's knowledge; the next test run writes a new set (D-107).
export async function clearKnowledgeQuestions(agentId: string) {
  const supabase = await supabaseServer();
  await supabase.from("eval_scenarios").delete().eq("agent_id", agentId).eq("spec->>source", "generated");
  revalidatePath(`/agents/${agentId}`);
}

export async function setAgentEnabled(agentId: string, enabled: boolean) {
  const supabase = await supabaseServer();
  await supabase.from("agents").update({ enabled }).eq("id", agentId);
  revalidatePath(`/agents/${agentId}`);
}
