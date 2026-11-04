import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Card, CardHeader, EmptyState, PageHeader } from "@/components/ui";
import { AddKnowledge, AskBox, AutoRefresh, SourceActions } from "@/components/knowledge-ui";
import { time } from "@/lib/format";
import { deleteSource, retrySource } from "./actions";

const STATUS = {
  queued: { tone: "neutral", label: "Waiting" },
  parsing: { tone: "neutral", label: "Reading" },
  indexing: { tone: "neutral", label: "Indexing" },
  testing: { tone: "neutral", label: "Checking" },
  ready: { tone: "success", label: "Ready" },
  needs_review: { tone: "warning", label: "Needs review" },
  failed: { tone: "danger", label: "Failed" },
} as const;

type Stats = { pages?: number; checked_at?: string; refreshed_at?: string; check_error?: string | null; chunks?: number; tokens?: number; tables?: { name: string; rows: number }[]; quality?: { tested: number; hit_rate: number; failed: { question: string; passage: string }[] } };

export default async function KnowledgePage() {
  const supabase = await supabaseServer();
  const { data: sources, error } = await supabase
    .from("knowledge_sources")
    .select("id,name,source_type,file_kind,url,status,error,parsed_md,stats,created_at")
    .order("created_at", { ascending: false });
  const busy = sources?.some((s) => ["queued", "parsing", "indexing", "testing"].includes(s.status)) ?? false;

  return (
    <>
      <PageHeader title="Knowledge" intro="What your agents know. Add it once, then choose which agents use it." />
      <AutoRefresh active={busy} />
      {error && <p role="alert" className="text-[13px] text-danger-fg">Knowledge is not available yet: the database update for it has not been applied.</p>}

      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[999_1_480px] min-w-0 flex flex-col gap-6">
          <AddKnowledge />
          {!sources?.length ? (
            <EmptyState text="Nothing added yet. Upload a document or paste your questions and answers above." />
          ) : (
            <Card className="overflow-hidden">
              <CardHeader title="Your knowledge" caption={`${sources.length} item${sources.length === 1 ? "" : "s"}`} />
              <ul>
                {sources.map((s) => {
                  const st = STATUS[s.status as keyof typeof STATUS] ?? STATUS.queued;
                  const stats = (s.stats ?? {}) as Stats;
                  return (
                    <li key={s.id} className="px-5 py-4 border-b border-line-subtle last:border-b-0 flex flex-col gap-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex flex-col gap-1 min-w-0">
                          <span className="text-sm font-medium flex flex-wrap items-center gap-2">
                            {s.name} <Badge tone={st.tone}>{st.label}</Badge>
                          </span>
                          <span className="font-mono text-xs text-ink-muted">
                            {s.source_type === "file" ? s.file_kind?.toUpperCase() : s.source_type === "url" ? s.url : s.source_type === "faq" ? "Q&A" : "Text"} · {time(s.created_at)}
                            {stats.pages ? ` · ${stats.pages} pages` : ""}
                            {stats.chunks ? ` · ${stats.chunks} sections` : ""}
                            {stats.tables?.length ? ` · ${stats.tables.map((t) => `${t.name}: ${t.rows} rows`).join(", ")}` : ""}
                          </span>
                        </div>
                        <SourceActions id={s.id} canRetry={s.status === "failed" || s.status === "needs_review"} onRetry={retrySource} onDelete={deleteSource} />
                      </div>
                      {s.error && <p className="text-[13px] text-danger-fg">{s.error}</p>}
                      {s.source_type === "url" && s.status === "ready" && (
                        <p className="text-[13px] text-ink-muted">
                          {/* Websites are re-read weekly and re-indexed when they change (D-108). */}
                          {stats.checked_at ? `Checked for website changes on ${time(stats.checked_at)}` : "Checked for changes once a week"}
                          {stats.refreshed_at ? ` · updated from the website on ${time(stats.refreshed_at)}` : ""}
                          {stats.check_error ? ` · last check: ${stats.check_error} The earlier content is still used.` : ""}
                        </p>
                      )}
                      {stats.quality && stats.quality.tested > 0 && (
                        <p className="text-[13px] text-ink-muted">
                          Checked with {stats.quality.tested} test questions: {Math.round(stats.quality.hit_rate * 100)}% found the right passage.
                        </p>
                      )}
                      {s.status === "needs_review" && stats.quality?.failed?.length ? (
                        <ul className="text-[13px] text-ink-secondary flex flex-col gap-1.5">
                          {stats.quality.failed.map((f, i) => (
                            <li key={i} className="rounded-md bg-warning-bg text-warning-fg px-3 py-2">
                              Not found: &ldquo;{f.question}&rdquo;<br />
                              <span className="opacity-90">in: {f.passage}...</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {s.parsed_md && (
                        <details className="border border-line rounded-md text-[13px]">
                          <summary className="px-3 py-2 cursor-pointer text-ink-secondary">What was read from this</summary>
                          <pre className="px-3 pb-3 whitespace-pre-wrap font-sans leading-[1.55] max-h-72 overflow-y-auto">{s.parsed_md.slice(0, 6000)}</pre>
                        </details>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </div>
        <aside className="flex-[1_1_320px] min-w-0">
          <AskBox sources={(sources ?? []).filter((s) => s.status === "ready").map((s) => ({ id: s.id, name: s.name }))} />
        </aside>
      </div>
    </>
  );
}
