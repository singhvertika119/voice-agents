import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Card, CardHeader, EmptyState, PageHeader } from "@/components/ui";
import { AddToolForm, TestToolForm, ToolButton } from "@/components/tools-ui";
import { deleteTool, setToolEnabled } from "./actions";

export default async function ToolsPage() {
  const supabase = await supabaseServer();
  const { data: tools, error } = await supabase
    .from("tools")
    .select("id,name,description,endpoint,method,timeout_ms,requires_confirmation,enabled,auth_header")
    .order("created_at", { ascending: false });
  return (
    <>
      <PageHeader title="Tools" intro="Actions your agents can take in your own systems." />
      {error && <p role="alert" className="text-[13px] text-danger-fg">Tools are not available yet: the database update for them has not been applied.</p>}
      <div className="flex flex-wrap gap-6 items-start">
        <div className="flex-[999_1_480px] min-w-0 flex flex-col gap-6">
          {!tools?.length ? (
            <EmptyState text="No tools yet. Add one to let an agent check orders, book appointments or save leads in your system." />
          ) : (
            <Card className="overflow-hidden">
              <CardHeader title="Your tools" caption="Test a tool here, then tick it on an agent's Tools tab." />
              <ul>
                {tools.map((t) => (
                  <li key={t.id} className="px-5 py-4 border-b border-line-subtle last:border-b-0 flex flex-col gap-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-sm font-medium flex flex-wrap items-center gap-2">
                          <span className="font-mono">{t.name}</span>
                          {t.enabled ? <Badge tone="success">On</Badge> : <Badge>Off</Badge>}
                          {t.requires_confirmation && <Badge tone="warning">Asks to confirm</Badge>}
                        </span>
                        <span className="text-[13px] text-ink-muted">{t.description}</span>
                        <span className="font-mono text-xs text-ink-muted break-all">{t.method} {t.endpoint} · {t.timeout_ms / 1000}s limit{t.auth_header ? " · credential saved" : ""}</span>
                      </div>
                      <div className="flex gap-2">
                        <ToolButton label={t.enabled ? "Turn off" : "Turn on"} onClick={setToolEnabled.bind(null, t.id, !t.enabled)} />
                        <ToolButton label="Delete" danger onClick={deleteTool.bind(null, t.id)} />
                      </div>
                    </div>
                    <TestToolForm id={t.id} />
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <aside className="flex-[1_1_360px] min-w-0"><AddToolForm /></aside>
      </div>
    </>
  );
}
