"use client";

import { useActionState, useEffect, useRef, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";
import { Button, Card, Field, inputCls, textareaCls } from "@/components/ui";
import { addScenario, type ScenarioState } from "@/app/(app)/agents/test-runs";

export function AutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), 4000);
    return () => clearInterval(t);
  }, [active, router]);
  return null;
}

export function AddScenarioForm({ agentId }: { agentId: string }) {
  const [state, action, pending] = useActionState<ScenarioState, FormData>(addScenario.bind(null, agentId), null);
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state?.ok) form.current?.reset();
  }, [state]);
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
          {state && (
            <p role={state.ok ? "status" : "alert"} className={`text-[13px] inline-flex items-center gap-1.5 ${state.ok ? "text-success-fg" : "text-danger-fg"}`}>
              {state.ok && <Check size={14} strokeWidth={2.5} aria-hidden />} {state.message}
            </p>
          )}
        </div>
      </form>
    </Card>
  );
}

export function RunButton({ label, run }: { label: string; run: () => Promise<void> }) {
  const [pending, start] = useTransition();
  return <Button disabled={pending} onClick={() => start(() => run())}>{pending ? "Starting..." : label}</Button>;
}

export function SmallButton({ label, run, confirmText }: { label: string; run: () => Promise<void>; confirmText?: string }) {
  const [pending, start] = useTransition();
  return (
    <Button variant="secondary" className="h-9" disabled={pending} onClick={() => { if (!confirmText || confirm(confirmText)) start(() => run()); }}>
      {label}
    </Button>
  );
}
