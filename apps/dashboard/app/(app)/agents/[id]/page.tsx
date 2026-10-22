import Link from "next/link";
import { notFound } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Button, Card, CardHeader } from "@/components/ui";
import { findPlaceholders, type AgentConfig } from "@/lib/agent-config";
import { time } from "@/lib/format";
import { TestPanel } from "@/components/test-panel";
import { AgentEditor, type SourceOption, type ToolOption } from "@/components/agent-editor";
import { AddScenarioForm, AutoRefresh, RunButton, SmallButton } from "@/components/tests-ui";
import { publish } from "../actions";
import { deleteScenario, queueTests, setAgentEnabled } from "../test-runs";

type Scenario = { name: string; source: string; runs: number; pass_rate: number; required: number; passed: boolean; results: { run: number; passed: boolean; fixed: Record<string, boolean>; judge: { reason?: string }; transcript: { speaker: string; text: string }[]; error?: string | null }[] };
type RunRow = { id: string; agent_version: number; status: string; passed: boolean | null; pass_rate: number | null; p95_reply_ms: number | null; results: { scenarios?: Scenario[]; scenarios_passed?: number; scenarios_total?: number; note?: string } | null; error: string | null; created_at: string };

const NICE: Record<string, string> = {
  no_error: "no technical error", agent_replied: "agent replied", says_expected_words: "gave the expected answer", avoids_forbidden_words: "avoided forbidden words",
  replies_in_callers_language: "replied in the caller's language", short_enough_for_voice: "short enough to listen to", booked_only_after_a_yes: "booked only after a clear yes",
};
const nice = (k: string) => NICE[k] ?? k.replace(/^called_/, "used the ").replace(/^did_not_call_/, "did not use the ").replaceAll("_", " ");

export default async function AgentBuilder({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; error?: string; live?: string }>;
}) {
  const { id } = await params;
  const { tab = "instructions", error, live } = await searchParams;
  const supabase = await supabaseServer();
  const onVersions = tab === "versions", onTests = tab === "tests";
  const onEditor = !onVersions && !onTests;
  const nothing = Promise.resolve({ data: null as null });
  // All queries start together (each one is a round trip to the database), and each tab asks only for what it shows.
  const [{ data: agent }, { data: versions }, { data: srcRows }, { data: toolRows }, { data: member }, { data: runRows }, { data: scenarioRows }] = await Promise.all([
    supabase.from("agents").select("id,name,published_version,enabled").eq("id", id).single(),
    supabase.from("agent_versions").select("version,status,config,note,created_at,published_at").eq("agent_id", id).order("version", { ascending: false }),
    onEditor ? supabase.from("knowledge_sources").select("id,name,status,stats").order("created_at", { ascending: false }) : nothing,
    onEditor ? supabase.from("tools").select("id,name,description,enabled,requires_confirmation").order("name") : nothing,
    onVersions ? supabase.from("tenant_members").select("role").limit(1).single() : nothing,
    onVersions || onTests ? supabase.from("eval_runs").select("id,agent_version,status,passed,pass_rate,p95_reply_ms,results,error,created_at").eq("agent_id", id).order("created_at", { ascending: false }).limit(10) : nothing,
    onTests ? supabase.from("eval_scenarios").select("id,name,spec").or(`agent_id.eq.${id},agent_id.is.null`).order("created_at", { ascending: false }) : nothing,
  ]);
  if (!agent) notFound();
  const latest = versions?.[0];
  const cfg = latest?.config as AgentConfig;
  const hasDraft = latest?.status === "draft";
  const sources: SourceOption[] = (srcRows ?? []).map((r) => ({ id: r.id, name: r.name, status: r.status, chunks: Number((r.stats as { chunks?: number })?.chunks ?? 0) }));
  const tools = (toolRows ?? []) as ToolOption[];
  const canOverride = ["owner", "admin"].includes(member?.role ?? "");
  const editing = tab === "voice" ? "voice" : tab === "knowledge" ? "knowledge" : tab === "tools" ? "tools" : "instructions";
  const runs = (runRows ?? []) as RunRow[];
  const latestRunFor = (v: number) => runs.find((r) => r.agent_version === v);
  const running = runs.some((r) => r.status === "queued" || r.status === "running");

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-[13px] text-ink-muted"><Link href="/agents" className="hover:text-ink inline-flex items-center min-h-11 pr-1">Agents</Link> / {agent.name}</p>
          <h1 className="text-xl font-semibold mt-1 flex flex-wrap items-center gap-3">
            {agent.name}
            {agent.enabled === false && <Badge tone="danger">Paused</Badge>}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {hasDraft ? (
            <span className="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-warning-bg text-warning-fg text-[13px] font-medium">
              <span className="size-[7px] rounded-full bg-warning-dot" aria-hidden />
              Editing draft v{latest.version}{agent.published_version ? ` · Live is v${agent.published_version}` : " · Not live yet"}
            </span>
          ) : (
            agent.published_version && <Badge tone="success">{`Live v${agent.published_version}`}</Badge>
          )}
          <SmallButton
            label={agent.enabled === false ? "Resume agent" : "Pause agent"}
            run={setAgentEnabled.bind(null, id, agent.enabled === false)}
            confirmText={agent.enabled === false ? undefined : "Pause this agent? New callers will hear that the service is not available. Calls in progress continue."}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[999_1_480px] min-w-0 flex flex-col gap-4">
          {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}
          {live && !error && (
            <p role="status" className="px-3 py-2 rounded-md bg-success-bg text-success-fg text-[13px]">Your agent is live. New calls now use this version. Phone numbers are connected separately; until then, test it from the panel on the right.</p>
          )}

          {!["versions", "tests"].includes(tab) && cfg && <AgentEditor agentId={id} name={agent.name} cfg={cfg} sources={sources} tools={tools} initialTab={editing} />}

          {["versions", "tests"].includes(tab) && (
            <div className="flex flex-col gap-4">
              <div className="flex gap-1 border-b border-line overflow-x-auto whitespace-nowrap [&>*]:shrink-0">
                <Link href={`/agents/${id}`} className="h-10 px-3 text-sm text-ink-muted inline-flex items-center">&larr; Editing</Link>
                {[["versions", "Versions"], ["tests", "Tests"]].map(([t, label]) => (
                  <Link key={t} href={`/agents/${id}?tab=${t}`} className={`h-10 px-3 text-sm inline-flex items-center ${tab === t ? "text-ink font-medium border-b-2 border-ink -mb-px" : "text-ink-muted"}`}>{label}</Link>
                ))}
              </div>

              {tab === "versions" && (
                <Card className="overflow-hidden">
                  <CardHeader title="Versions" caption="Publishing makes a version live for the next call. Calls already in progress are not affected." />
                  <ul>
                    {versions?.map((v) => {
                      const r = latestRunFor(v.version);
                      return (
                        <li key={v.version} className="px-5 py-4 border-b border-line-subtle last:border-b-0 flex flex-wrap items-center justify-between gap-3">
                          <div className="flex flex-col gap-1">
                            <span className="text-sm font-medium flex flex-wrap items-center gap-2">
                              Version {v.version}
                              {v.status === "published" && <Badge tone="success">Live</Badge>}
                              {v.status === "draft" && <Badge tone="warning">Draft</Badge>}
                              {v.status === "archived" && <Badge>Earlier</Badge>}
                              {r && (r.status === "done" ? <Badge tone={r.passed ? "success" : "danger"}>{r.passed ? "Tests passed" : "Tests failed"}</Badge> : r.status === "failed" ? <Badge tone="danger">Tests could not run</Badge> : <Badge>Testing</Badge>)}
                            </span>
                            <span className="font-mono text-xs text-ink-muted">{time(v.created_at)}{v.note ? ` · ${v.note}` : ""}</span>
                          </div>
                          {v.status !== "published" && (
                            <div className="flex flex-wrap gap-2">
                              <form action={publish.bind(null, id, v.version, false)}>
                                <Button variant="secondary">{v.status === "draft" ? "Publish" : "Make live again"}</Button>
                              </form>
                              {canOverride && (
                                <form action={publish.bind(null, id, v.version, true)}>
                                  <Button variant="text" title="Publish even if the test conversations did not pass. This is recorded.">Publish anyway</Button>
                                </form>
                              )}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </Card>
              )}

              {tab === "tests" && (
                <>
                  <AutoRefresh active={running} />
                  <Card className="p-5 flex flex-col gap-3">
                    <h2 className="text-base font-semibold">Test conversations</h2>
                    <p className="text-sm leading-[1.55] text-ink-secondary">
                      An AI plays a caller and talks to this agent many times: asking for a person, asking things it should not know, trying to trick it, and asking the questions in your knowledge. Each answer is checked. Run this before you publish a change.
                    </p>
                    <div className="flex flex-wrap items-center gap-3">
                      {latest && <RunButton label={`Run tests on version ${latest.version}`} run={queueTests.bind(null, id, latest.version)} />}
                      {running && <span className="text-[13px] text-ink-muted">Running. This takes a few minutes. The test worker window must be open.</span>}
                    </div>
                  </Card>

                  {runs.length === 0 ? (
                    <Card className="p-5 text-sm text-ink-muted">No test runs yet.</Card>
                  ) : (
                    runs.map((r) => (
                      <Card key={r.id} className="overflow-hidden">
                        <div className="px-5 py-4 flex flex-wrap items-center justify-between gap-3 border-b border-line">
                          <div className="flex flex-col gap-1">
                            <span className="text-sm font-semibold flex flex-wrap items-center gap-2">
                              Version {r.agent_version}
                              {r.status === "done" ? <Badge tone={r.passed ? "success" : "danger"}>{r.passed ? "Passed" : "Failed"}</Badge> : r.status === "failed" ? <Badge tone="danger">Could not run</Badge> : <Badge>{r.status === "queued" ? "Waiting" : "Running"}</Badge>}
                            </span>
                            <span className="font-mono text-xs text-ink-muted">
                              {time(r.created_at)}
                              {r.status === "done" && r.results ? ` · ${r.results.scenarios_passed}/${r.results.scenarios_total} scenarios passed · slowest 5% of replies ${r.p95_reply_ms != null ? (r.p95_reply_ms / 1000).toFixed(1) + " s" : "-"}` : ""}
                            </span>
                          </div>
                        </div>
                        {r.error && <p className="px-5 py-3 text-[13px] text-danger-fg">{r.error}</p>}
                        {r.results?.scenarios && (
                          <ul>
                            {r.results.scenarios.map((s, i) => (
                              <li key={i} className="px-5 py-3 border-b border-line-subtle last:border-b-0">
                                <details>
                                  <summary className="cursor-pointer flex flex-wrap items-center justify-between gap-2 text-sm">
                                    <span className="flex flex-wrap items-center gap-2"><Badge tone={s.passed ? "success" : "danger"}>{s.passed ? "Pass" : "Fail"}</Badge>{s.name.replaceAll("_", " ")}</span>
                                    <span className="font-mono text-xs text-ink-muted">{Math.round(s.pass_rate * 100)}% of {s.runs}</span>
                                  </summary>
                                  <div className="mt-3 flex flex-col gap-3 text-[13px]">
                                    {s.results.filter((x) => !x.passed).slice(0, 2).map((x) => (
                                      <div key={x.run} className="rounded-md bg-danger-bg text-danger-fg px-3 py-2">
                                        <p className="font-medium">Attempt {x.run} failed</p>
                                        <p>{Object.entries(x.fixed).filter(([, ok]) => !ok).map(([k]) => `Did not: ${nice(k)}`).join(". ") || x.judge.reason}</p>
                                        {x.judge.reason && <p className="opacity-90">Reviewer: {x.judge.reason}</p>}
                                        {x.error && <p>{x.error}</p>}
                                        {x.transcript.length > 0 && (
                                          <div className="mt-2 flex flex-col gap-1 text-ink">
                                            {x.transcript.slice(0, 12).map((t, j) => <p key={j}><span className="text-ink-muted">{t.speaker === "caller" ? "Caller" : "Agent"}:</span> {t.text}</p>)}
                                          </div>
                                        )}
                                      </div>
                                    ))}
                                    {s.passed && <p className="text-ink-muted">All attempts passed.</p>}
                                  </div>
                                </details>
                              </li>
                            ))}
                          </ul>
                        )}
                        {r.results?.note && <p className="px-5 py-3 text-[13px] text-ink-muted border-t border-line">{r.results.note}</p>}
                      </Card>
                    ))
                  )}

                  {(scenarioRows?.length ?? 0) > 0 && (
                    <Card className="overflow-hidden">
                      <CardHeader title="Your own tests" />
                      <ul>
                        {scenarioRows!.map((s) => (
                          <li key={s.id} className="px-5 py-3 border-b border-line-subtle last:border-b-0 flex items-center justify-between gap-3 text-sm">
                            <span>{s.name}<span className="block text-[13px] text-ink-muted">{(s.spec as { caller_says?: string }).caller_says}</span></span>
                            <SmallButton label="Delete" run={deleteScenario.bind(null, id, s.id)} confirmText="Delete this test?" />
                          </li>
                        ))}
                      </ul>
                    </Card>
                  )}
                  <AddScenarioForm agentId={id} />
                </>
              )}
            </div>
          )}
        </div>

        <aside className="flex-[1_1_320px] min-w-0">
          <TestPanel agentId={id} hasLive={!!agent.published_version} hasDraft={hasDraft} placeholders={cfg ? findPlaceholders(cfg) : []} />
        </aside>
      </div>
    </>
  );
}
