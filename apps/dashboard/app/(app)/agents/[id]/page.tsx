import Link from "next/link";
import { notFound } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Button, Card, CardHeader } from "@/components/ui";
import { findPlaceholders, type AgentConfig } from "@/lib/agent-config";
import { time } from "@/lib/format";
import { TestPanel } from "@/components/test-panel";
import { AgentEditor, type SourceOption, type ToolOption } from "@/components/agent-editor";
import { AddScenarioForm, AutoRefresh, RunButton, SmallButton } from "@/components/tests-ui";
import { deleteAgent, publish } from "../actions";
import { clearKnowledgeQuestions, deleteScenario, queueTests, setAgentEnabled } from "../test-runs";

type Scenario = { name: string; source: string; runs: number; pass_rate: number; required: number; passed: boolean; results: { run: number; passed: boolean; fixed: Record<string, boolean>; judge: { reason?: string }; transcript: { speaker: string; text: string }[]; error?: string | null }[] };
type Progress = { stage: "preparing" | "talking"; done: number; total: number; passed: number; updated_at: string };
type RunRow = { id: string; agent_version: number; status: string; passed: boolean | null; pass_rate: number | null; p95_reply_ms: number | null; results: { scenarios?: Scenario[]; scenarios_passed?: number; scenarios_total?: number; note?: string; progress?: Progress; scheduled?: boolean } | null; error: string | null; created_at: string };

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
    onTests ? supabase.from("eval_scenarios").select("id,name,spec,agent_id").or(`agent_id.eq.${id},agent_id.is.null`).order("created_at", { ascending: false }) : nothing,
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
  // A run nobody has picked up for a few minutes means no test runner is on (D-103); say so instead of "Waiting" forever.
  const notPicked = (r: RunRow) => r.status === "queued" && waitedMinutes(r.created_at) >= 3;
  const stuck = runs.some(notPicked);
  // A nightly check that scores lower than the previous nightly check of the same version: nothing in the version
  // changed, so a provider, the website or the saved questions did (D-108).
  const dropFor = (r: RunRow) => {
    if (!r.results?.scheduled || r.status !== "done" || r.pass_rate == null) return null;
    const prev = runs.find((x) => x.created_at < r.created_at && x.results?.scheduled && x.status === "done" && x.agent_version === r.agent_version && x.pass_rate != null);
    return prev && prev.pass_rate! - r.pass_rate >= 0.1 ? prev : null;
  };
  const generated = (scenarioRows ?? []).filter((s) => (s.spec as { source?: string })?.source === "generated" && s.agent_id === id);
  const own = (scenarioRows ?? []).filter((s) => (s.spec as { source?: string })?.source !== "generated");

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
            label="Delete agent"
            run={deleteAgent.bind(null, id)}
            confirmText={`Delete "${agent.name}"? Its versions, test runs and what it remembers about callers are removed and cannot be brought back.${agent.published_version ? " It is live, so new calls to it will stop being answered." : ""} Past calls are kept. Your knowledge and tools are not touched.`}
          />
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
                      An AI plays a caller and talks to this agent many times: asking for a person, asking things it should not know, trying to trick it, and asking the questions in your knowledge. Each answer is checked. Run this before you publish a change. The live version is also checked every night at 2 am when it took calls that week.
                    </p>
                    <div className="flex flex-wrap items-center gap-3">
                      {latest && <RunButton label={`Run tests on version ${latest.version}`} run={queueTests.bind(null, id, latest.version)} />}
                      {running && !stuck && <span className="text-[13px] text-ink-muted">A run takes about 5 to 10 minutes. You can leave this page; the result is saved here.</span>}
                    </div>
                  </Card>

                  {stuck && (
                    <p role="status" className="px-3 py-2.5 rounded-md bg-warning-bg text-warning-fg text-[13px] leading-[1.55]">
                      A test run has been waiting for more than 3 minutes, so the test runner is not on. It runs on the background
                      server when that server has enough memory (setting RUN_TEST_WORKER=1), or on your computer with
                      scripts/run-evals.ps1. Waiting runs start by themselves as soon as it is on; nothing is lost.
                    </p>
                  )}
                  {runs.length === 0 ? (
                    <Card className="p-5 text-sm text-ink-muted">No test runs yet.</Card>
                  ) : (
                    runs.map((r) => (
                      <Card key={r.id} className="overflow-hidden">
                        <div className="px-5 py-4 flex flex-wrap items-center justify-between gap-3 border-b border-line">
                          <div className="flex flex-col gap-1">
                            <span className="text-sm font-semibold flex flex-wrap items-center gap-2">
                              Version {r.agent_version}
                              {r.results?.scheduled && <Badge>Nightly check</Badge>}
                              {r.status === "done" ? <Badge tone={r.passed ? "success" : "danger"}>{r.passed ? "Passed" : "Failed"}</Badge> : r.status === "failed" ? <Badge tone="danger">Could not run</Badge> : <Badge tone={notPicked(r) ? "warning" : "neutral"}>{r.status === "queued" ? (notPicked(r) ? "Not started" : "Waiting") : "Running"}</Badge>}
                            </span>
                            <span className="font-mono text-xs text-ink-muted">
                              {time(r.created_at)}
                              {r.status === "done" && r.results ? ` · ${r.results.scenarios_passed}/${r.results.scenarios_total} scenarios passed · slowest 5% of replies ${r.p95_reply_ms != null ? (r.p95_reply_ms / 1000).toFixed(1) + " s" : "-"}` : ""}
                            </span>
                          </div>
                        </div>
                        {(() => {
                          const prev = dropFor(r);
                          return prev && (
                            <p role="status" className="px-5 py-3 text-[13px] bg-warning-bg text-warning-fg">
                              Score fell from {Math.round(prev.pass_rate! * 100)}% to {Math.round(r.pass_rate! * 100)}% since the last nightly check, and this version was not changed.
                              Something around it changed: the AI or voice provider, a website in its knowledge, or its test questions. Open the failed tests below to see what it now gets wrong.
                            </p>
                          );
                        })()}
                        {(r.status === "running" || (r.status === "queued" && !notPicked(r))) && <RunProgress run={r} />}
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

                  <Card className="overflow-hidden">
                    <CardHeader
                      title="Questions from your knowledge"
                      caption={generated.length
                        ? "Written once from this agent's knowledge and asked in every run, so scores can be compared between versions. A new set is written when the knowledge changes."
                        : "The next test run writes these from this agent's knowledge and keeps them for later runs."}
                      action={generated.length ? <SmallButton label="Write new questions" run={clearKnowledgeQuestions.bind(null, id)} confirmText="Remove these questions? The next test run writes a new set, so its score will not be comparable with earlier runs." /> : undefined}
                    />
                    {generated.length > 0 && (
                      <ul>
                        {generated.map((s) => {
                          const g = s.spec as { kind?: string; question?: string };
                          const kind = g.kind === "answerable" ? ["Should answer", "success"] : g.kind === "unanswerable" ? ["Not in knowledge", "neutral"] : ["Wrong claim to correct", "warning"];
                          return (
                            <li key={s.id} className="px-5 py-3 border-b border-line-subtle last:border-b-0 flex items-center justify-between gap-3 text-sm">
                              <span className="flex flex-col gap-1 min-w-0">
                                <span><Badge tone={kind[1] as "success" | "neutral" | "warning"}>{kind[0]}</Badge></span>
                                <span className="break-words">{g.question}</span>
                              </span>
                              <SmallButton label="Remove" run={deleteScenario.bind(null, id, s.id)} confirmText="Remove this question from future test runs?" />
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </Card>

                  {own.length > 0 && (
                    <Card className="overflow-hidden">
                      <CardHeader title="Your own tests" />
                      <ul>
                        {own.map((s) => (
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

function waitedMinutes(iso: string) {
  return (Date.now() - new Date(iso).getTime()) / 60_000;
}

// Live progress for a run in progress (D-105). The worker saves it after every finished conversation, and the page
// refreshes every few seconds, so the bar moves while the run goes. No movement for 5 minutes is called out, so a
// stopped runner is not mistaken for a slow one.
function RunProgress({ run }: { run: RunRow }) {
  const p = run.results?.progress;
  const started = waitedMinutes(run.created_at);
  const quiet = p ? waitedMinutes(p.updated_at) : started;
  const pct = p && p.total ? Math.round((p.done / p.total) * 100) : 0;
  const left = p && p.done > 0 && p.total > p.done ? Math.max(1, Math.round(((started / p.done) * (p.total - p.done)))) : null;
  const step = run.status === "queued"
    ? "Waiting for the test runner to pick this up. This usually takes a few seconds."
    : !p || p.stage === "preparing"
      ? "Getting ready: loading this version and writing test questions from your knowledge."
      : `${p.done} of ${p.total} test conversations finished${p.done ? ` · ${p.passed} passed so far` : ""}`;
  return (
    <div className="px-5 py-4 flex flex-col gap-2.5" role="status" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
        <span className="text-ink-secondary">{step}</span>
        <span className="font-mono text-xs text-ink-muted tabular-nums">
          {run.status === "running" ? `started ${minutes(started)} ago${left ? ` · about ${left} min left` : ""}` : ""}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden" aria-hidden>
        <div className={`h-full rounded-full bg-ink transition-[width] duration-700 ${!p || p.stage === "preparing" ? "w-1/12 animate-pulse" : ""}`} style={p?.stage === "talking" ? { width: `${Math.max(pct, 2)}%` } : undefined} />
      </div>
      {run.status === "running" && quiet >= 5 ? (
        <p className="text-[13px] text-warning-fg">No progress for {minutes(quiet)}. The test runner may have stopped; if this does not move in a few minutes, run the tests again.</p>
      ) : (
        <p className="text-xs text-ink-muted">An AI caller is talking to this version and every answer is checked. You can leave this page; the result is saved here.</p>
      )}
    </div>
  );
}

function minutes(m: number) {
  return m < 1 ? "under a minute" : `${Math.round(m)} min`;
}
