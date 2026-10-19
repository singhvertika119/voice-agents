"use client";

import { useActionState, useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { Badge, Button, Card, Field, textareaCls } from "@/components/ui";
import { VOICES, findPlaceholders, type AgentConfig } from "@/lib/agent-config";
import { saveDraft, type SaveState } from "@/app/(app)/agents/actions";

export type SourceOption = { id: string; name: string; status: string; chunks: number };
export type ToolOption = { id: string; name: string; description: string; enabled: boolean; requires_confirmation: boolean };
type Tab = "instructions" | "voice" | "knowledge" | "tools";
const TABS: { id: Tab; label: string }[] = [
  { id: "instructions", label: "Instructions" },
  { id: "voice", label: "Voice" },
  { id: "knowledge", label: "Knowledge" },
  { id: "tools", label: "Tools" },
];

// One form for all editing tabs, so switching tabs never throws away what you typed.
export function AgentEditor({ agentId, cfg, sources, tools, initialTab }: { agentId: string; cfg: AgentConfig; sources: SourceOption[]; tools: ToolOption[]; initialTab: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [state, action, pending] = useActionState<SaveState, FormData>(saveDraft.bind(null, agentId), null);
  const [text, setText] = useState({ greeting: cfg.greeting, instructions: cfg.instructions, knowledge: cfg.knowledge });
  const [picked, setPicked] = useState<string[]>(cfg.knowledge_sources ?? []);
  const [pickedTools, setPickedTools] = useState<string[]>(cfg.tool_ids ?? []);
  const placeholders = findPlaceholders(text);
  const show = (t: Tab) => (tab === t ? "" : "hidden");

  return (
    <form action={action} className="flex flex-col gap-5">
      <div className="flex gap-1 border-b border-line" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`h-10 px-3 text-sm ${tab === t.id ? "text-ink font-medium border-b-2 border-ink -mb-px" : "text-ink-muted"}`}
          >
            {t.label}
          </button>
        ))}
        <Link href={`/agents/${agentId}?tab=versions`} className="h-10 px-3 text-sm text-ink-muted inline-flex items-center">Versions</Link>
        <Link href={`/agents/${agentId}?tab=tests`} className="h-10 px-3 text-sm text-ink-muted inline-flex items-center">Tests</Link>
      </div>

      {placeholders.length > 0 && (
        <p role="status" className="px-3 py-2 rounded-md bg-warning-bg text-warning-fg text-[13px]">
          Replace {placeholders.slice(0, 4).join(", ")}{placeholders.length > 4 ? " and more" : ""} with your own details. The agent reads these out loud.
        </p>
      )}

      <Card className={`p-5 flex flex-col gap-5 ${show("instructions")}`}>
        <Field label="Greeting" helper="The first thing callers hear. Keep it short and say it is an AI assistant.">
          <textarea name="greeting" rows={3} value={text.greeting} onChange={(e) => setText({ ...text, greeting: e.target.value })} className={textareaCls} />
        </Field>
        <Field label="Instructions" helper="How the agent should behave and what it must never do.">
          <textarea name="instructions" rows={7} value={text.instructions} onChange={(e) => setText({ ...text, instructions: e.target.value })} className={textareaCls} />
        </Field>
      </Card>

      <div className={`grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4 ${show("voice")}`} role="radiogroup" aria-label="Voice">
        {VOICES.map((v) => (
          <VoiceTile key={v.id} id={v.id} label={v.label} note={v.note} initial={cfg.voice.tts_primary.speaker === v.id} />
        ))}
      </div>

      <div className={`flex flex-col gap-4 ${show("knowledge")}`}>
        <Card className="p-5 flex flex-col gap-4">
          <div>
            <h2 className="text-base font-semibold">Documents and websites</h2>
            <p className="text-[13px] text-ink-muted">Choose what this agent may answer from. <Link href="/knowledge" className="underline">Add or manage knowledge</Link></p>
          </div>
          <input type="hidden" name="sources_present" value="1" />
          {sources.length === 0 ? (
            <p className="text-sm text-ink-muted">Nothing added yet.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {sources.map((s) => {
                const usable = s.status === "ready";
                return (
                  <li key={s.id} className="flex items-start gap-3 text-sm leading-snug">
                    <input
                      type="checkbox"
                      name="source"
                      value={s.id}
                      disabled={!usable}
                      checked={picked.includes(s.id)}
                      onChange={(e) => setPicked(e.target.checked ? [...picked, s.id] : picked.filter((x) => x !== s.id))}
                      className="mt-0.5 size-4 accent-ink"
                      id={`src-${s.id}`}
                    />
                    <label htmlFor={`src-${s.id}`} className="flex flex-wrap items-center gap-2">
                      {s.name}
                      <Badge tone={usable ? "success" : s.status === "failed" ? "danger" : "neutral"}>{usable ? "Ready" : s.status === "failed" ? "Failed" : s.status === "needs_review" ? "Needs review" : "Indexing"}</Badge>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
        <Card className="p-5">
          <Field label="Extra notes" helper="Short facts that do not belong in a document: timings, prices, policies. Added to every answer.">
            <textarea name="knowledge" rows={8} value={text.knowledge} onChange={(e) => setText({ ...text, knowledge: e.target.value })} className={textareaCls} />
          </Field>
        </Card>
      </div>

      <div className={`flex flex-col gap-4 ${show("tools")}`}>
        <Card className="p-5 flex flex-col gap-4">
          <div>
            <h2 className="text-base font-semibold">Tools this agent can use</h2>
            <p className="text-[13px] text-ink-muted">Every agent can already ask for a person, book a callback and end the call. Tick extra actions in your own systems. <Link href="/tools" className="underline">Add or test tools</Link></p>
          </div>
          <input type="hidden" name="tools_present" value="1" />
          {tools.length === 0 ? (
            <p className="text-sm text-ink-muted">No tools added yet.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {tools.map((t) => (
                <li key={t.id} className="flex items-start gap-3 text-sm leading-snug">
                  <input
                    type="checkbox" name="tool" value={t.id} id={`tool-${t.id}`} disabled={!t.enabled}
                    checked={pickedTools.includes(t.id)}
                    onChange={(e) => setPickedTools(e.target.checked ? [...pickedTools, t.id] : pickedTools.filter((x) => x !== t.id))}
                    className="mt-0.5 size-4 accent-ink"
                  />
                  <label htmlFor={`tool-${t.id}`} className="flex flex-col gap-0.5">
                    <span className="font-medium flex flex-wrap items-center gap-2"><span className="font-mono">{t.name}</span>{t.requires_confirmation && <Badge tone="warning">Asks to confirm</Badge>}{!t.enabled && <Badge>Off</Badge>}</span>
                    <span className="text-[13px] text-ink-muted">{t.description}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <Button disabled={pending}>{pending ? "Saving..." : "Save draft"}</Button>
        {state && (
          <p role={state.ok ? "status" : "alert"} className={`text-[13px] ${state.ok ? "text-success-fg" : "text-danger-fg"} inline-flex items-center gap-1.5`}>
            {state.ok && <Check size={14} strokeWidth={2.5} aria-hidden />} {state.message}
          </p>
        )}
      </div>
    </form>
  );
}

function VoiceTile({ id, label, note, initial }: { id: string; label: string; note: string; initial: boolean }) {
  // The radio's checked state lives in the DOM; the border follows it through :has().
  return (
    <label className="relative bg-card rounded-xl p-5 flex flex-col gap-1 cursor-pointer border border-line has-[:checked]:border-2 has-[:checked]:border-ink">
      <input type="radio" name="voice" value={id} defaultChecked={initial} className="peer sr-only" />
      <span className="absolute top-3 right-3 size-5 rounded-full bg-ink text-on-ink hidden peer-checked:inline-flex items-center justify-center" aria-hidden>
        <Check size={12} strokeWidth={2.5} />
      </span>
      <span className="text-[15px] font-semibold">{label}</span>
      <span className="text-[13px] text-ink-muted">{note}</span>
    </label>
  );
}
