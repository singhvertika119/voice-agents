"use client";

import { useActionState } from "react";
import { Check } from "lucide-react";
import { Button, Card, Field, inputCls } from "@/components/ui";
import { eraseCaller, saveSettings, type FormState } from "@/app/(app)/settings/actions";

export type SettingsValues = {
  days: number[]; start: string; end: string; handoff_phone: string; retention_days: number;
  max_concurrent_calls: number; memory_enabled: boolean; require_tests: boolean; record_calls: boolean;
};
const DAYS = [[1, "Mon"], [2, "Tue"], [3, "Wed"], [4, "Thu"], [5, "Fri"], [6, "Sat"], [7, "Sun"]] as const;

function Result({ state }: { state: FormState }) {
  if (!state) return null;
  return (
    <p role={state.ok ? "status" : "alert"} className={`text-[13px] inline-flex items-center gap-1.5 ${state.ok ? "text-success-fg" : "text-danger-fg"}`}>
      {state.ok && <Check size={14} strokeWidth={2.5} aria-hidden />} {state.message}
    </p>
  );
}

export function SettingsForm({ v, canEdit }: { v: SettingsValues; canEdit: boolean }) {
  const [state, action, pending] = useActionState<FormState, FormData>(saveSettings, null);
  return (
    <form action={action} className="flex flex-col gap-6">
      <Card className="p-5 flex flex-col gap-5">
        <div>
          <h2 className="text-base font-semibold">Business hours and handoff</h2>
          <p className="text-[13px] text-ink-muted">When your team can take calls. Outside these hours the agent offers a callback instead. Times are IST.</p>
        </div>
        <fieldset className="flex flex-wrap gap-2" disabled={!canEdit}>
          <legend className="text-sm font-medium mb-2">Working days</legend>
          {DAYS.map(([n, label]) => (
            <label key={n} className="min-h-10 px-3.5 inline-flex items-center gap-2 rounded-full border text-sm border-line-strong has-[:checked]:border-ink has-[:checked]:bg-muted">
              <input type="checkbox" name="days" value={n} defaultChecked={v.days.includes(n)} className="accent-ink" /> {label}
            </label>
          ))}
        </fieldset>
        <div className="flex flex-wrap gap-4">
          <Field label="Opens (IST)"><input type="time" name="start" defaultValue={v.start} disabled={!canEdit} className={`${inputCls} font-mono w-40`} /></Field>
          <Field label="Closes (IST)"><input type="time" name="end" defaultValue={v.end} disabled={!canEdit} className={`${inputCls} font-mono w-40`} /></Field>
        </div>
        <Field label="Team phone number" helper="Where handoffs will ring once phone lines are connected. Until then the agent books a callback.">
          <div className="flex gap-2">
            <span className="h-11 px-3 inline-flex items-center rounded-md border border-line-strong bg-muted font-mono text-sm">+91</span>
            <input name="handoff_phone" defaultValue={v.handoff_phone} disabled={!canEdit} inputMode="numeric" placeholder="98765 43210" className={`${inputCls} font-mono text-sm max-w-60`} />
          </div>
        </Field>
      </Card>

      <Card className="p-5 flex flex-col gap-5">
        <h2 className="text-base font-semibold">Limits and publishing</h2>
        <Field label="Calls at the same time" helper="When all lines are busy, new callers hear a short message and are asked to call back.">
          <input type="number" name="max_concurrent_calls" min={1} max={500} defaultValue={v.max_concurrent_calls} disabled={!canEdit} className={`${inputCls} w-32 font-mono`} />
        </Field>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="require_tests" defaultChecked={v.require_tests} disabled={!canEdit} className="mt-0.5 size-4 accent-ink" />
          <span>
            <span className="font-medium">Only publish agents that pass the test conversations</span><br />
            <span className="text-[13px] text-ink-muted">Owners and admins can still publish anyway, and it is recorded.</span>
          </span>
        </label>
      </Card>

      <Card className="p-5 flex flex-col gap-5">
        <div>
          <h2 className="text-base font-semibold">Privacy</h2>
          <p className="text-[13px] text-ink-muted">Callers are told they are speaking to an AI and that calls may be recorded. Check the wording with your lawyer.</p>
        </div>
        <Field label="Keep transcripts for (days)" helper="Older transcripts are deleted automatically. Summaries stay.">
          <input type="number" name="retention_days" min={1} max={3650} defaultValue={v.retention_days} disabled={!canEdit} className={`${inputCls} w-32 font-mono`} />
        </Field>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="record_calls" defaultChecked={v.record_calls} disabled={!canEdit} className="mt-0.5 size-4 accent-ink" />
          <span>
            <span className="font-medium">Record calls</span><br />
            <span className="text-[13px] text-ink-muted">Audio is kept in your private storage for the same number of days as transcripts, and only your team can play it. Callers are told at the start of every call that it may be recorded.</span>
          </span>
        </label>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="memory_enabled" defaultChecked={v.memory_enabled} disabled={!canEdit} className="mt-0.5 size-4 accent-ink" />
          <span>
            <span className="font-medium">Remember returning callers</span><br />
            <span className="text-[13px] text-ink-muted">A short summary of earlier calls helps the agent continue where it left off.</span>
          </span>
        </label>
      </Card>

      <div className="flex flex-wrap items-center gap-4">
        <Button disabled={pending || !canEdit}>{pending ? "Saving..." : "Save settings"}</Button>
        <Result state={state} />
        {!canEdit && <span className="text-[13px] text-ink-muted">Only owners and admins can change these.</span>}
      </div>
    </form>
  );
}

export function EraseForm({ canEdit }: { canEdit: boolean }) {
  const [state, action, pending] = useActionState<FormState, FormData>(eraseCaller, null);
  return (
    <Card className="p-5 flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Delete a caller&apos;s data</h2>
        <p className="text-[13px] text-ink-muted">When someone asks you to erase their data, enter their number. Their calls, transcripts, saved profile and callback requests are removed together.</p>
      </div>
      <form action={action} className="flex flex-col gap-4">
        <Field label="Caller's mobile number">
          <div className="flex gap-2">
            <span className="h-11 px-3 inline-flex items-center rounded-md border border-line-strong bg-muted font-mono text-sm">+91</span>
            <input name="phone" inputMode="numeric" placeholder="98765 43210" disabled={!canEdit} className={`${inputCls} font-mono text-sm max-w-60`} />
          </div>
        </Field>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="confirm" disabled={!canEdit} className="mt-0.5 size-4 accent-ink" /> I understand this cannot be undone.
        </label>
        <div className="flex flex-wrap items-center gap-4">
          <Button variant="secondary" disabled={pending || !canEdit}>{pending ? "Deleting..." : "Delete their data"}</Button>
          <Result state={state} />
        </div>
      </form>
    </Card>
  );
}
