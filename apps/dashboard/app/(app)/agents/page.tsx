import Link from "next/link";
import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Button, ButtonLink, Card, CardHeader, EmptyState, Field, PageHeader, inputCls } from "@/components/ui";
import { time } from "@/lib/format";
import { createAgent } from "./actions";

export default async function AgentsPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const supabase = await supabaseServer();
  const { data: agents } = await supabase
    .from("agents")
    .select("id,name,published_version,updated_at")
    .order("updated_at", { ascending: false });

  return (
    <>
      <PageHeader title="Agents" intro="Each agent answers calls on its own, with its own voice and knowledge." action={<ButtonLink href="/onboarding/business-type" variant="secondary">Guided setup</ButtonLink>} />
      {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}

      <Card className="p-5">
        <form action={createAgent} className="flex flex-wrap items-end gap-4">
          <div className="flex-[1_1_280px]">
            <Field label="Agent name" helper="Callers never see this. It helps you tell agents apart.">
              <input name="name" placeholder="Front desk" className={inputCls} />
            </Field>
          </div>
          <Button>Create agent</Button>
        </form>
      </Card>

      {!agents?.length ? (
        <EmptyState text="No agents yet. Create your first agent to start taking calls." />
      ) : (
        <Card className="overflow-hidden">
          <CardHeader title="Your agents" />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-sm">
              <thead>
                <tr>
                  {["Agent", "Status", "Updated"].map((h, i) => (
                    <th key={h} className={`px-3 py-3 bg-subtle text-left text-xs font-medium text-ink-muted border-b border-line ${i === 0 ? "px-5" : ""}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => (
                  <tr key={a.id}>
                    <td className="px-5 py-3.5 border-b border-line-subtle">
                      <Link href={`/agents/${a.id}`} className="font-medium text-ink hover:underline inline-flex items-center min-h-11">{a.name}</Link>
                    </td>
                    <td className="px-3 py-3.5 border-b border-line-subtle">
                      {a.published_version ? <Badge tone="success">{`Live v${a.published_version}`}</Badge> : <Badge tone="warning">Draft</Badge>}
                    </td>
                    <td className="px-3 py-3.5 border-b border-line-subtle font-mono text-[13px]">{time(a.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
