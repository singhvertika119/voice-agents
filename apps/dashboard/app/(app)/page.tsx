import Link from "next/link";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, ButtonLink, Card, CardHeader, EmptyState, MetricTile, PageHeader } from "@/components/ui";
import { count, inr } from "@/lib/format";

export default async function Home() {
  const supabase = await supabaseServer();
  const since = new Date(Date.now() - 7 * 864e5).toISOString();
  const [{ data: calls }, { data: agents }] = await Promise.all([
    supabase.from("calls").select("outcome,avg_reply_ms,cost_usd").gte("started_at", since),
    supabase.from("agents").select("id,name,published_version"),
  ]);
  const total = calls?.length ?? 0;
  const resolved = calls?.filter((c) => c.outcome === "resolved").length ?? 0;
  const handed = calls?.filter((c) => c.outcome === "handed_off").length ?? 0;
  const replies = calls?.map((c) => c.avg_reply_ms).filter((x): x is number => x != null) ?? [];
  const avgReply = replies.length ? replies.reduce((a, b) => a + b, 0) / replies.length / 1000 : null;
  const spent = calls?.reduce((s, c) => s + Number(c.cost_usd ?? 0), 0) ?? 0;
  const needsLive = agents?.filter((a) => !a.published_version) ?? [];

  return (
    <>
      <PageHeader title="Home" intro="How your agents did in the last 7 days." />

      <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-4">
        <MetricTile label="Calls answered" value={count(total)} />
        <MetricTile label="Resolved" value={total ? `${Math.round((resolved / total) * 100)}%` : "-"} note="Without a person" />
        <MetricTile label="Handed to your team" value={count(handed)} />
        <MetricTile label="Average reply time" value={avgReply == null ? "-" : `${avgReply.toFixed(1)} s`} />
        <MetricTile label="Spent" value={inr(spent)} />
      </div>

      {!agents?.length ? (
        <EmptyState text="No agents yet. Create an agent to start answering calls." action={<ButtonLink href="/agents">Create an agent</ButtonLink>} />
      ) : (
        <Card>
          <CardHeader title="Needs your attention" />
          {needsLive.length === 0 ? (
            <p className="px-5 py-4 text-sm text-ink-muted">Nothing needs attention right now.</p>
          ) : (
            needsLive.map((a) => (
              <div key={a.id} className="px-5 py-4 border-b border-line-subtle last:border-b-0 flex flex-col gap-1.5">
                <span className="text-sm font-medium flex items-center gap-2">
                  <span className="size-2 rounded-full bg-warning-dot" aria-hidden /> {a.name} is not live yet <Badge tone="warning">Draft</Badge>
                </span>
                <span className="text-[13px] text-ink-muted">Publish a version so it can answer calls.</span>
                <Link href={`/agents/${a.id}?tab=versions`} className="text-sm text-ink-secondary hover:text-ink underline w-fit">Review and publish</Link>
              </div>
            ))
          )}
        </Card>
      )}
    </>
  );
}
