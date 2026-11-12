"use client";

import { useActionState, useRef, useTransition } from "react";
import { Button, Card, Field, FormResult, inputCls, textareaCls } from "@/components/ui";
import { useResetOnOk } from "@/components/client-ui";
import { addScenario } from "@/app/(app)/agents/test-runs";
import type { ActionState } from "@/lib/action-state";

export function AddScenarioForm({ agentId }: { agentId: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(addScenario.bind(null, agentId), null);
  const form = useRef<HTMLFormElement>(null);
  useResetOnOk(state, form);
  return (
    <Card className="p-5 flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Add your own test</h2>
        <p className="text-[13px] text-ink-muted">Write something a caller really asks. Every test run plays it against this agent and checks the answer.</p>
      </div>
      <form ref={form} action={action} className="flex flex-col gap-4">
        <Field label="The caller says"><textarea name="caller_says" rows={2} required className={textareaCls} placeholder="Admission ke liye kitni fees lagti hai?" /></Field>
        <Field label="Answer must include one of (optional)" helper="Words separated by commas, for example: 600, six hundred, chhe sau"><input name="must_say" className={inputCls} /></Field>
        <Field label="Answer must never include (optional)" helper="For example: discount, free"><input name="must_not_say" className={inputCls} /></Field>
        <Field label="Name (optional)"><input name="name" className={inputCls} /></Field>
        <div className="flex flex-wrap items-center gap-4">
          <Button disabled={pending}>{pending ? "Adding..." : "Add test"}</Button>
          <FormResult state={state} />
        </div>
      </form>
    </Card>
  );
}

export function RunButton({ label, run }: { label: string; run: () => Promise<void> }) {
  const [pending, start] = useTransition();
  return <Button disabled={pending} onClick={() => start(() => run())}>{pending ? "Starting..." : label}</Button>;
}
