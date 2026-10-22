import Link from "next/link";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Card, CardHeader, EmptyState, PageHeader } from "@/components/ui";
import { duration, inr, time } from "@/lib/format";

const OUTCOME = {
  resolved: { tone: "success", label: "Resolved" },
  handed_off: { tone: "warning", label: "Handed off" },
  dropped: { tone: "danger", label: "Dropped" },
  callback: { tone: "neutral", label: "Callback" },
} as const;

export default async function CallsPage() {
  const supabase = await supabaseServer();
  const { data: calls } = await supabase
    .from("calls")
    .select("id,started_at,duration_s,outcome,caller_number,channel,cost_usd,agent_version,agents(name)")
    .order("started_at", { ascending: false })
    .limit(50);

  return (
    <>
      <PageHeader title="Calls" intro="Every call, with what was said." />
      {!calls?.length ? (
        <EmptyState text="No calls yet. Talk to an agent in the playground and your first call will show up here." />
      ) : (
        <Card className="overflow-hidden">
          <CardHeader title="Recent calls" />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr>
                  {["When (IST)", "Agent", "Caller", "Length", "Outcome", "Cost"].map((h, i) => (
                    <th key={h} className={`px-3 py-3 bg-subtle text-left text-xs font-medium text-ink-muted border-b border-line ${i === 0 ? "px-5" : ""}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => {
                  const o = c.outcome ? OUTCOME[c.outcome as keyof typeof OUTCOME] : null;
                  const agent = c.agents as unknown as { name: string } | null;
                  return (
                    <tr key={c.id}>
                      <td className="px-5 py-3.5 border-b border-line-subtle">
                        <Link href={`/calls/${c.id}`} className="font-medium hover:underline inline-flex items-center min-h-11">{time(c.started_at)}</Link>
                      </td>
                      <td className="px-3 py-3.5 border-b border-line-subtle">
                        {agent?.name ?? "Deleted agent"}<div className="font-mono text-xs text-ink-muted">v{c.agent_version}</div>
                      </td>
                      <td className="px-3 py-3.5 border-b border-line-subtle font-mono text-[13px]">{c.caller_number ?? "Browser test"}</td>
                      <td className="px-3 py-3.5 border-b border-line-subtle font-mono text-[13px]">{duration(c.duration_s)}</td>
                      <td className="px-3 py-3.5 border-b border-line-subtle">{o ? <Badge tone={o.tone}>{o.label}</Badge> : <Badge>In progress</Badge>}</td>
                      <td className="px-3 py-3.5 border-b border-line-subtle font-mono text-[13px]">{inr(c.cost_usd)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
