import Link from "next/link";
import { notFound } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Card, CardHeader } from "@/components/ui";
import { duration, inr, time } from "@/lib/format";

export default async function CallDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await supabaseServer();
  const { data: call } = await supabase.from("calls").select("*, agents(name)").eq("id", id).single();
  if (!call) notFound();
  const { data: turns } = await supabase.from("call_turns").select("seq,speaker,text,at_ms,latency_ms").eq("call_id", id).order("seq");
  const agent = call.agents as { name: string } | null;
  const st = call.structured as { intent?: string; commitments?: string[]; open_items?: string[] } | null;
  const tools = (call.tool_calls ?? []) as { tool: string; ok: boolean; ms: number }[];
  const facts: [string, string][] = [
    ["Agent version", `v${call.agent_version}`],
    ["Language", call.language ?? "-"],
    ["Duration", duration(call.duration_s)],
    ["Average reply time", call.avg_reply_ms ? `${(call.avg_reply_ms / 1000).toFixed(1)} s` : "-"],
    ["Cost", inr(call.cost_usd)],
  ];

  return (
    <>
      <div>
        <p className="text-[13px] text-ink-muted"><Link href="/calls" className="hover:text-ink">Calls</Link> / {time(call.started_at)}</p>
        <div className="flex flex-wrap items-center gap-3 mt-1">
          <h1 className="text-xl font-semibold">{agent?.name}</h1>
          {call.outcome && <Badge tone={call.outcome === "resolved" ? "success" : call.outcome === "dropped" ? "danger" : "warning"}>{({ resolved: "Resolved", handed_off: "Handed off", callback: "Callback booked", dropped: "Dropped" } as Record<string, string>)[call.outcome] ?? call.outcome}</Badge>}
        </div>
      </div>

      <div className="flex flex-wrap gap-6 items-start">
        <Card className="flex-[999_1_480px] min-w-0">
          <CardHeader title="Transcript" />
          <div className="p-5 flex flex-col gap-4" aria-live="polite">
            {!turns?.length && <p className="text-sm text-ink-muted">No transcript was saved for this call.</p>}
            {turns?.map((t) => (
              <div key={t.seq} className="flex gap-3">
                <span className="w-11 shrink-0 font-mono text-xs text-ink-muted pt-1">{duration((t.at_ms ?? 0) / 1000)}</span>
                <div className={`flex-1 flex flex-col gap-1 ${t.speaker === "caller" ? "items-end" : ""}`}>
                  <span className="text-xs font-medium text-ink-muted">{t.speaker === "caller" ? "Caller" : "Agent"}</span>
                  <p className={`text-sm leading-[1.55] ${t.speaker === "caller" ? "px-3.5 py-2.5 rounded-lg bg-muted" : ""}`}>{t.text}</p>
                  {t.speaker === "agent" && t.latency_ms != null && (
                    <span className="px-2 py-[3px] rounded-sm border border-line text-xs text-ink-secondary font-mono w-fit">{(t.latency_ms / 1000).toFixed(1)} s</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>

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
