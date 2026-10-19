import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Card } from "@/components/ui";
import { AddKnowledge, AskBox, AutoRefresh } from "@/components/knowledge-ui";
import { WizardFooter } from "@/components/wizard";
import { finishKnowledge } from "../actions";

const STATUS: Record<string, { tone: "neutral" | "success" | "warning" | "danger"; label: string }> = {
  queued: { tone: "neutral", label: "Waiting" }, parsing: { tone: "neutral", label: "Reading" }, indexing: { tone: "neutral", label: "Indexing" },
  testing: { tone: "neutral", label: "Checking" }, ready: { tone: "success", label: "Ready" }, needs_review: { tone: "warning", label: "Needs review" }, failed: { tone: "danger", label: "Failed" },
};

export default async function KnowledgeStep({ searchParams }: { searchParams: Promise<{ agent?: string; error?: string }> }) {
  const { agent, error } = await searchParams;
  if (!agent) redirect("/onboarding/business-type");
  const supabase = await supabaseServer();
  const { data: sources } = await supabase.from("knowledge_sources").select("id,name,status,error").order("created_at", { ascending: false });
  const busy = sources?.some((s) => ["queued", "parsing", "indexing", "testing"].includes(s.status)) ?? false;
  return (
    <div className="flex flex-col gap-7 flex-1">
      <AutoRefresh active={busy} />
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">What should your agent know?</h1>
        <p className="text-[15px] text-ink-muted mt-2">Add your fee list, FAQs, a brochure or a web page. Short and clear works best. You can add more any time, and you can skip this for now.</p>
      </div>
      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[999_1_460px] min-w-0 flex flex-col gap-5">
          {/* AddKnowledge and AskBox are forms of their own, so the Continue button gets a separate form below (forms cannot nest) */}
          <AddKnowledge />
          {!!sources?.length && (
            <Card className="overflow-hidden">
              <ul>
                {sources.map((s) => {
                  const st = STATUS[s.status] ?? STATUS.queued;
                  return (
                    <li key={s.id} className="px-5 py-3.5 border-b border-line-subtle last:border-b-0 flex flex-col gap-1">
                      <span className="text-sm font-medium flex flex-wrap items-center gap-2">{s.name} <Badge tone={st.tone}>{st.label}</Badge></span>
                      {s.error && <span className="text-[13px] text-danger-fg">{s.error}</span>}
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </div>
        <aside className="flex-[1_1_320px] min-w-0"><AskBox /></aside>
      </div>
      {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}
      <form action={finishKnowledge.bind(null, agent)} className="mt-auto flex flex-col">
        <WizardFooter backHref={`/onboarding/details?agent=${agent}`} primary={sources?.some((s) => s.status === "ready") ? "Continue" : "Skip for now"} pending={busy} />
      </form>
    </div>
  );
}
