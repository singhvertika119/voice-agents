"use client";

import { useActionState, useEffect, useRef, useTransition } from "react";
import { Check } from "lucide-react";
import { Button, Card, Field, inputCls, textareaCls } from "@/components/ui";
import { addTool, testTool, type ToolState } from "@/app/(app)/tools/actions";

function Msg({ s }: { s: ToolState }) {
  if (!s) return null;
  return (
    <p role={s.ok ? "status" : "alert"} className={`text-[13px] inline-flex items-start gap-1.5 ${s.ok ? "text-success-fg" : "text-danger-fg"}`}>
      {s.ok && <Check size={14} strokeWidth={2.5} aria-hidden className="mt-0.5 shrink-0" />} <span>{s.message}</span>
    </p>
  );
}

export function AddToolForm() {
  const [state, action, pending] = useActionState<ToolState, FormData>(addTool, null);
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state?.ok) form.current?.reset();
  }, [state]);
  return (
    <Card className="p-5 flex flex-col gap-5">
      <div>
        <h2 className="text-base font-semibold">Add a tool</h2>
        <p className="text-[13px] text-ink-muted">A tool lets the agent do something in your own system, such as check an order or book a slot. You provide a web address; the agent sends it the details it collected.</p>
      </div>
      <form ref={form} action={action} className="flex flex-col gap-4">
        <Field label="Name" helper="Letters, numbers and underscores. For example: check_order_status">
          <input name="name" required className={`${inputCls} font-mono text-sm`} placeholder="check_order_status" />
        </Field>
        <Field label="When should the agent use it?" helper="One or two sentences. The agent reads this to decide.">
          <textarea name="description" required rows={2} className={textareaCls} placeholder="Look up the status of a customer's order when they give an order number." />
        </Field>
        <Field label="Web address (https)" helper="Must be a public https address. Private or internal addresses are blocked.">
          <input name="endpoint" type="url" required className={`${inputCls} font-mono text-sm`} placeholder="https://api.yourshop.in/orders/status" />
        </Field>
        <div className="flex flex-wrap gap-4">
          <Field label="Method">
            <select name="method" className="h-11 px-3 rounded-md border border-line-strong bg-card text-[15px]"><option>POST</option><option>GET</option></select>
          </Field>
          <Field label="Time limit (ms)" helper="500 to 5000">
            <input name="timeout_ms" type="number" min={500} max={5000} defaultValue={4000} className={`${inputCls} w-32 font-mono`} />
          </Field>
        </div>
        <Field label="Details the agent must collect" helper="One per line: name | type | what it is | required. Types: string, number, boolean.">
          <textarea name="params" rows={3} className={`${textareaCls} font-mono text-[13px]`} placeholder={"order_id | string | The order number the caller gave | yes"} />
        </Field>
        <div className="flex flex-wrap gap-4">
          <Field label="Credential header (optional)" helper="For example Authorization">
            <input name="auth_header" className={`${inputCls} font-mono text-sm`} placeholder="Authorization" />
          </Field>
          <Field label="Credential value (optional)" helper="Stored encrypted. You cannot read it back.">
            <input name="secret" type="password" autoComplete="off" className={`${inputCls} font-mono text-sm`} placeholder="Bearer ..." />
          </Field>
        </div>
        <Field label="Say while it runs (optional)" helper="Played so the caller is never met with silence. For example: Ek second, check karti hoon.">
          <input name="filler_phrase" className={inputCls} />
        </Field>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="requires_confirmation" className="mt-0.5 size-4 accent-ink" />
          <span><span className="font-medium">Ask the caller to confirm first</span><br /><span className="text-[13px] text-ink-muted">Use for anything that changes something: bookings, cancellations, payments. The agent reads the details back and waits for a yes.</span></span>
        </label>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="idempotent" className="mt-0.5 size-4 accent-ink" />
          <span><span className="font-medium">Safe to repeat</span><br /><span className="text-[13px] text-ink-muted">Tick only if sending the same request twice does no harm (lookups). Then a failed request is tried once more.</span></span>
        </label>
        <div className="flex flex-wrap items-center gap-4">
          <Button disabled={pending}>{pending ? "Adding..." : "Add tool"}</Button>
          <Msg s={state} />
        </div>
      </form>
    </Card>
  );
}

export function TestToolForm({ id }: { id: string }) {
  const [state, action, pending] = useActionState<ToolState, FormData>(testTool.bind(null, id), null);
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input name="sample" aria-label="Sample details as JSON" placeholder='{"order_id": "4821"}' className={`${inputCls} h-10 font-mono text-[13px] flex-[1_1_220px]`} />
      <Button variant="secondary" className="h-10" disabled={pending}>{pending ? "Testing..." : "Test"}</Button>
      <div className="basis-full"><Msg s={state} /></div>
    </form>
  );
}

export function ToolButton({ label, onClick, danger }: { label: string; onClick: () => Promise<void>; danger?: boolean }) {
  const [pending, start] = useTransition();
  return (
    <Button
      variant="secondary"
      className="h-9"
      disabled={pending}
      onClick={() => {
        if (danger && !confirm("Delete this tool? Agents using it will stop using it.")) return;
        start(() => onClick());
      }}
    >
      {label}
    </Button>
  );
}
