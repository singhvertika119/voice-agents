import { supabaseServer } from "@/lib/supabase/server";
import { Badge, Button, Card, CardHeader, EmptyState, PageHeader } from "@/components/ui";
import { time } from "@/lib/format";
import { setCallbackStatus } from "./actions";

export default async function CallbacksPage() {
  const supabase = await supabaseServer();
  const { data: rows } = await supabase
    .from("callbacks")
    .select("id,phone_e164,preferred_time,reason,status,created_at,call_id")
    .order("created_at", { ascending: false })
    .limit(100);
  const open = rows?.filter((r) => r.status === "open").length ?? 0;
  return (
    <>
      <PageHeader title="Callbacks" intro="People who asked for your team to call them back." />
      {!rows?.length ? (
        <EmptyState text="No callback requests yet. They appear here when a caller asks for a person." />
      ) : (
        <Card className="overflow-hidden">
          <CardHeader title="Requests" caption={`${open} waiting`} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead>
                <tr>
                  {["Asked (IST)", "Number", "Preferred time", "About", "Status", ""].map((h, i) => (
                    <th key={i} className={`px-3 py-3 bg-subtle text-left text-xs font-medium text-ink-muted border-b border-line ${i === 0 ? "px-5" : ""}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="px-5 py-3.5 border-b border-line-subtle font-mono text-[13px]">{time(r.created_at)}</td>
                    <td className="px-3 py-3.5 border-b border-line-subtle font-mono text-[13px]">{r.phone_e164 ? r.phone_e164.replace(/^\+91(\d{5})(\d{5})$/, "+91 $1 $2") : "-"}</td>
                    <td className="px-3 py-3.5 border-b border-line-subtle">{r.preferred_time || "-"}</td>
                    <td className="px-3 py-3.5 border-b border-line-subtle max-w-[260px]">{r.reason || "-"}</td>
                    <td className="px-3 py-3.5 border-b border-line-subtle">
                      <Badge tone={r.status === "open" ? "warning" : "neutral"}>{r.status === "open" ? "Waiting" : r.status === "done" ? "Done" : "Cancelled"}</Badge>
                    </td>
                    <td className="px-3 py-3.5 border-b border-line-subtle text-right">
                      {r.status === "open" ? (
                        <form action={setCallbackStatus.bind(null, r.id, "done")}><Button variant="secondary" className="h-9">Mark done</Button></form>
                      ) : (
                        <form action={setCallbackStatus.bind(null, r.id, "open")}><Button variant="text" className="h-9">Reopen</Button></form>
                      )}
                    </td>
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
