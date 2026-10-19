import Link from "next/link";
import { notFound } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Button, Card, CardHeader } from "@/components/ui";
import { findPlaceholders, type AgentConfig } from "@/lib/agent-config";
import { time } from "@/lib/format";
import { TestPanel } from "@/components/test-panel";
import { AgentEditor, type SourceOption } from "@/components/agent-editor";
import { publish } from "../actions";

export default async function AgentBuilder({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; error?: string }>;
}) {
  const { id } = await params;
  const { tab = "instructions", error } = await searchParams;
  const supabase = await supabaseServer();
  const { data: agent } = await supabase.from("agents").select("id,name,published_version").eq("id", id).single();
  if (!agent) notFound();
  const { data: versions } = await supabase
    .from("agent_versions")
    .select("version,status,config,note,created_at,published_at")
    .eq("agent_id", id)
    .order("version", { ascending: false });
  const latest = versions?.[0];
  const cfg = latest?.config as AgentConfig;
  const hasDraft = latest?.status === "draft";
  const { data: srcRows } = await supabase.from("knowledge_sources").select("id,name,status,stats").order("created_at", { ascending: false });
  const sources: SourceOption[] = (srcRows ?? []).map((r) => ({ id: r.id, name: r.name, status: r.status, chunks: Number((r.stats as { chunks?: number })?.chunks ?? 0) }));
  const editing = tab === "voice" ? "voice" : tab === "knowledge" ? "knowledge" : "instructions";

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-[13px] text-ink-muted"><Link href="/agents" className="hover:text-ink">Agents</Link> / {agent.name}</p>
          <h1 className="text-xl font-semibold mt-1">{agent.name}</h1>
        </div>
        {hasDraft ? (
          <span className="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-warning-bg text-warning-fg text-[13px] font-medium">
            <span className="size-[7px] rounded-full bg-warning-dot" aria-hidden />
            Editing draft v{latest.version}{agent.published_version ? ` · Live is v${agent.published_version}` : " · Not live yet"}
          </span>
        ) : (
          agent.published_version && <Badge tone="success">{`Live v${agent.published_version}`}</Badge>
        )}
      </div>

      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[999_1_480px] min-w-0 flex flex-col gap-4">
          {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}

          {tab !== "versions" && cfg && <AgentEditor agentId={id} cfg={cfg} sources={sources} initialTab={editing} />}

          {tab === "versions" && (
            <>
            <Link href={`/agents/${id}`} className="text-sm text-ink-secondary hover:text-ink w-fit">&larr; Back to editing</Link>
            <Card className="overflow-hidden">
              <CardHeader title="Versions" caption="Publishing makes a version live for the next call. Calls already in progress are not affected." />
              <ul>
                {versions?.map((v) => (
                  <li key={v.version} className="px-5 py-4 border-b border-line-subtle last:border-b-0 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-col gap-1">
                      <span className="text-sm font-medium flex items-center gap-2">
                        Version {v.version}
                        {v.status === "published" && <Badge tone="success">Live</Badge>}
                        {v.status === "draft" && <Badge tone="warning">Draft</Badge>}
                        {v.status === "archived" && <Badge>Earlier</Badge>}
                      </span>
                      <span className="font-mono text-xs text-ink-muted">{time(v.created_at)}{v.note ? ` · ${v.note}` : ""}</span>
                    </div>
                    {v.status !== "published" && (
                      <form action={publish.bind(null, id, v.version)}>
                        <Button variant="secondary">{v.status === "draft" ? "Publish" : "Make live again"}</Button>
                      </form>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
            </>
          )}
        </div>

        <aside className="flex-[1_1_320px] min-w-0">
          <TestPanel agentId={id} hasLive={!!agent.published_version} hasDraft={hasDraft} placeholders={cfg ? findPlaceholders(cfg) : []} />
        </aside>
      </div>
    </>
  );
}
