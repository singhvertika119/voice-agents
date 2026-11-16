"use client";

import { useActionState } from "react";
import { Badge, Button, Card, Field, FormResult, inputCls } from "@/components/ui";
import { eraseCaller, recheckOpenAIKey, removeOpenAIKey, saveKeyUse, saveOpenAIKey, saveSettings } from "@/app/(app)/settings/actions";
import type { ActionState } from "@/lib/action-state";
import type { KeyStatus, KeyUse } from "@/lib/openai-key";

export type SettingsValues = {
  days: number[]; start: string; end: string; handoff_phone: string; retention_days: number;
  max_concurrent_calls: number; memory_enabled: boolean; require_tests: boolean; record_calls: boolean;
};
const DAYS = [[1, "Mon"], [2, "Tue"], [3, "Wed"], [4, "Thu"], [5, "Fri"], [6, "Sat"], [7, "Sun"]] as const;

export function SettingsForm({ v, canEdit }: { v: SettingsValues; canEdit: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(saveSettings, null);
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
          <p className="text-[13px] text-ink-muted">The greeting is spoken exactly as you write it. If callers should be told they are speaking to an AI or that calls are recorded, say so in the greeting, and check the wording with your lawyer.</p>
        </div>
        <Field label="Keep transcripts for (days)" helper="Older transcripts are deleted automatically. Summaries stay.">
          <input type="number" name="retention_days" min={1} max={3650} defaultValue={v.retention_days} disabled={!canEdit} className={`${inputCls} w-32 font-mono`} />
        </Field>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="record_calls" defaultChecked={v.record_calls} disabled={!canEdit} className="mt-0.5 size-4 accent-ink" />
          <span>
            <span className="font-medium">Record calls</span><br />
            <span className="text-[13px] text-ink-muted">Audio is kept in your private storage for the same number of days as transcripts, and only your team can play it.</span>
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
        <FormResult state={state} />
        {!canEdit && <span className="text-[13px] text-ink-muted">Only owners and admins can change these.</span>}
      </div>
    </form>
  );
}

export function EraseForm({ canEdit }: { canEdit: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(eraseCaller, null);
  return (
    <Card className="p-5 flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Delete a caller&apos;s data</h2>
        <p className="text-[13px] text-ink-muted">When someone asks you to erase their data, enter their number. Their calls, transcripts, saved profile and callback requests are removed together.</p>
      </div>
      <form action={action} className="flex flex-col gap-4">
        <Field label="Caller's number" helper="An Indian mobile: 10 digits. A number outside India: start with + and the country code, for example +1 415 555 0100.">
          <input name="phone" inputMode="tel" placeholder="98765 43210" disabled={!canEdit} className={`${inputCls} font-mono text-sm max-w-60`} />
        </Field>
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input type="checkbox" name="confirm" disabled={!canEdit} className="mt-0.5 size-4 accent-ink" /> I understand this cannot be undone.
        </label>
        <div className="flex flex-wrap items-center gap-4">
          <Button variant="secondary" disabled={pending || !canEdit}>{pending ? "Deleting..." : "Delete their data"}</Button>
          <FormResult state={state} />
        </div>
      </form>
    </Card>
  );
}

export type OpenAIKeyInfo = { last4: string; status: KeyStatus; checked_at: string | null; use_for: KeyUse } | null;

const KEY_USES = [
  ["calls", "Calls only (cheapest)", "Live calls, and the agent in test conversations, use OpenAI. Summaries, the test reviewer, knowledge checks and the knowledge chat use the free model."],
  ["everything", "Everything", "All of the above use OpenAI. Summaries and test reviews are a little more accurate, and it costs more."],
] as const;

const KEY_BADGE = {
  ok: ["success", "Working"], no_credits: ["warning", "No credits"], invalid: ["danger", "Not accepted"], unchecked: ["neutral", "Not checked yet"],
  could_not_decrypt: ["danger", "Could not be read, save it again"],
} as const;

// The workspace's own OpenAI key (D-124). The saved key is never sent back to the browser, only its last 4 characters.
export function OpenAIKeyForm({ info, canEdit }: { info: OpenAIKeyInfo; canEdit: boolean }) {
  const [state, save, saving] = useActionState<ActionState, FormData>(saveOpenAIKey, null);
  const [checkState, recheck, checking] = useActionState<ActionState>(recheckOpenAIKey, null);
  const [removeState, remove, removing] = useActionState<ActionState>(removeOpenAIKey, null);
  const [useForState, saveUse, savingUse] = useActionState<ActionState, FormData>(saveKeyUse, null);
  const [tone, label] = info ? KEY_BADGE[info.status] : (["neutral", "None"] as const);
  return (
    <Card className="p-5 flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Your OpenAI key</h2>
        <p className="text-[13px] text-ink-muted">
          Your agents use OpenAI on your own account, so you pay OpenAI directly. Without a working key they use a free
          model instead, which is a little less accurate. Get a key at platform.openai.com.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Saved key:</span>
        {info ? <span className="font-mono">sk-...{info.last4}</span> : <span className="text-ink-muted">none</span>}
        <Badge tone={tone}>{label}</Badge>
      </div>
      {info?.status === "no_credits" && (
        <p className="text-[13px] text-warning-fg">This OpenAI account has run out of credits. Add credits in OpenAI&apos;s billing settings, then press Check again.</p>
      )}
      {info?.status === "could_not_decrypt" && (
        <p className="text-[13px] text-danger-fg">The saved key could not be read (the server encryption key changed). Please save the key again.</p>
      )}
      <form action={save} className="flex flex-col gap-4">
        <Field label={info ? "Replace with a new key" : "OpenAI key"} helper="Starts with sk-. It is stored encrypted and is never shown again.">
          <input name="openai_key" type="password" autoComplete="off" spellCheck={false} placeholder="sk-..." disabled={!canEdit} className={`${inputCls} font-mono text-sm`} />
        </Field>
        <div className="flex flex-wrap items-center gap-4">
          <Button disabled={saving || !canEdit}>{saving ? "Checking..." : "Save key"}</Button>
          <FormResult state={state} />
        </div>
      </form>
      {info && (
        <form action={saveUse} className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2" disabled={!canEdit}>
            <legend className="text-sm font-medium mb-1">Use the key for</legend>
            {KEY_USES.map(([value, title, help]) => (
              <label key={value} className="flex items-start gap-3 text-sm leading-snug">
                <input type="radio" name="use_for" value={value} defaultChecked={info.use_for === value} className="mt-0.5 size-4 accent-ink" />
                <span><span className="font-medium">{title}</span><br /><span className="text-[13px] text-ink-muted">{help}</span></span>
              </label>
            ))}
          </fieldset>
          <div className="flex flex-wrap items-center gap-4">
            <Button variant="secondary" disabled={savingUse || !canEdit}>{savingUse ? "Saving..." : "Save choice"}</Button>
            <FormResult state={useForState} />
          </div>
        </form>
      )}
      {info && (
        <div className="flex flex-wrap items-center gap-3">
          <form action={recheck}><Button variant="secondary" disabled={checking || !canEdit}>{checking ? "Checking..." : "Check again"}</Button></form>
          <form action={remove}><Button variant="secondary" disabled={removing || !canEdit}>{removing ? "Removing..." : "Remove key"}</Button></form>
          <FormResult state={checkState ?? removeState} />
        </div>
      )}
    </Card>
  );
}
