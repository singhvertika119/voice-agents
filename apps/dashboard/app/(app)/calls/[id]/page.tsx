import Link from "next/link";
import { notFound } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Card, CardHeader } from "@/components/ui";
import { duration, inr, time } from "@/lib/format";
import { createClient } from "@supabase/supabase-js";
import { CallReview } from "@/components/call-review";

export default async function CallDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await supabaseServer();
  const [{ data: call }, { data: turns }] = await Promise.all([
    supabase.from("calls").select("*, agents(name)").eq("id", id).single(),
    supabase.from("call_turns").select("seq,speaker,text,at_ms,latency_ms").eq("call_id", id).order("seq"),
  ]);
  if (!call) notFound();
  const agent = call.agents as { name: string } | null;
  // The call row was read as the signed-in user, so row-level security already proved they may see this call.
  // The link works for 10 minutes and only for this one file.
  let audioUrl: string | null = null;
  if (call.recording_path) {
    const admin = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
    const { data: signed } = await admin.storage.from("recordings").createSignedUrl(call.recording_path, 600);
    audioUrl = signed?.signedUrl ?? null;
  }
  const st = call.structured as { intent?: string; commitments?: string[]; open_items?: string[] } | null;
  const tools = (call.tool_calls ?? []) as { tool: string; ok: boolean; ms: number }[];
  // Saved by the voice agent per caller turn (D-115). Calls from before then have none.
  type Timing = { wait: number; transcript: number; search: number; first_word: number; voice: number; total: number };
  // first_word is timed from the start of the model step, which begins with the search (D-116), so the model's own
  // part is first_word minus search.
  const replies = ((call.cost_breakdown as { replies?: Timing[] } | null)?.replies ?? [])
    .filter((r) => r && r.total != null)
    .map((r) => ({ ...r, first_word: Math.max(r.first_word - r.search, 0) }));
  const sec = (ms: number) => `${(ms / 1000).toFixed(2)}`;
  const slowest = (r: Timing) => (["wait", "search", "first_word", "voice"] as const).reduce((a, b) => (r[b] > r[a] ? b : a));
  const facts: [string, string][] = [
    ["Agent version", `v${call.agent_version}`],
    ["Language", call.language ?? "-"],
    ["Duration", duration(call.duration_s)],
    ["Recording", call.recording_path ? "Saved" : call.consent?.recording_stored === false ? "Not recorded" : "None"],
    ["Average reply time", call.avg_reply_ms ? `${(call.avg_reply_ms / 1000).toFixed(1)} s` : "-"],
    ["Cost", inr(call.cost_usd)],
  ];

  return (
    <>
      <div>
        <p className="text-[13px] text-ink-muted"><Link href="/calls" className="hover:text-ink inline-flex items-center min-h-11 pr-1">Calls</Link> / {time(call.started_at)}</p>
        <div className="flex flex-wrap items-center gap-3 mt-1">
          <h1 className="text-xl font-semibold">{agent?.name ?? "Deleted agent"}</h1>
          {call.outcome && <Badge tone={call.outcome === "resolved" ? "success" : call.outcome === "dropped" ? "danger" : "warning"}>{({ resolved: "Resolved", handed_off: "Handed off", callback: "Callback booked", dropped: "Dropped" } as Record<string, string>)[call.outcome] ?? call.outcome}</Badge>}
        </div>
      </div>

      <div className="flex flex-wrap gap-6 items-start">
        <CallReview turns={turns ?? []} audioUrl={audioUrl} seconds={call.recording_seconds ?? call.duration_s ?? 0} />

        <div className="flex-[1_1_320px] min-w-0 flex flex-col gap-4">
          <Card className="p-5">
            <h2 className="text-base font-semibold mb-2">Summary</h2>
            <p className="text-sm leading-[1.55] text-ink-secondary">{call.summary ?? "A summary appears here after the call is processed."}</p>
            {st && (
              <dl className="mt-4 flex flex-col gap-3 text-sm">
                {st.intent && <div><dt className="text-xs font-medium text-ink-muted">Wanted</dt><dd>{st.intent}</dd></div>}
                {!!st.commitments?.length && <div><dt className="text-xs font-medium text-ink-muted">Promised</dt><dd>{st.commitments.join("; ")}</dd></div>}
                {!!st.open_items?.length && <div><dt className="text-xs font-medium text-ink-muted">Still open</dt><dd>{st.open_items.join("; ")}</dd></div>}
              </dl>
            )}
          </Card>
          {tools.length > 0 && (
            <Card className="p-5">
              <h2 className="text-base font-semibold mb-3">What the agent did</h2>
              <ul className="flex flex-col gap-2 text-sm">
                {tools.map((t, i) => (
                  <li key={i} className="flex items-center justify-between gap-3">
                    <span className="font-mono text-[13px]">{t.tool}</span>
                    <span className="flex items-center gap-2"><Badge tone={t.ok ? "success" : "danger"}>{t.ok ? "Worked" : "Failed"}</Badge><span className="font-mono text-xs text-ink-muted">{t.ms} ms</span></span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {replies.length > 0 && (
            <Card className="p-5">
              <h2 className="text-base font-semibold">Reply times</h2>
              <p className="text-[13px] text-ink-muted mt-1 mb-3">
                Seconds per reply, from the caller going quiet to the agent&rsquo;s voice starting: waiting to be sure the caller has finished, the knowledge search, the model&rsquo;s first word, then the voice. The slowest part is in bold.
              </p>
              <div className="overflow-x-auto -mx-1">
                <table className="w-full text-[13px] font-mono">
                  <thead>
                    <tr className="text-left text-ink-muted font-sans text-xs">
                      <th className="font-medium px-1 py-1.5">#</th>
                      <th className="font-medium px-1 py-1.5" title="End of speech until the turn was taken as finished">Wait</th>
                      <th className="font-medium px-1 py-1.5" title="Time the model waited for the knowledge search">Search</th>
                      <th className="font-medium px-1 py-1.5" title="Model's first word">Model</th>
                      <th className="font-medium px-1 py-1.5" title="First audio from the voice">Voice</th>
                      <th className="font-medium px-1 py-1.5 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {replies.map((r, i) => {
                      const top = slowest(r);
                      const cell = (k: "wait" | "search" | "first_word" | "voice") => <td className={`px-1 py-1.5 ${k === top ? "font-semibold text-ink" : "text-ink-secondary"}`}>{sec(r[k])}</td>;
                      return (
                        <tr key={i} className="border-t border-line-subtle">
                          <td className="px-1 py-1.5 text-ink-muted">{i + 1}</td>
                          {cell("wait")}
                          {cell("search")}
                          {cell("first_word")}
                          {cell("voice")}
                          <td className="px-1 py-1.5 text-right">{sec(r.total)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
          <Card className="p-5">
            <h2 className="text-base font-semibold mb-3">Call facts</h2>
            <dl className="flex flex-col gap-2 text-sm">
              {facts.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4">
                  <dt className="text-ink-muted">{k}</dt>
                  <dd className="font-mono text-[13px]">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}
