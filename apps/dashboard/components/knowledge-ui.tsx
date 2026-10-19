"use client";

import { useActionState, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, FileUp } from "lucide-react";
import { Button, Card, Field, inputCls, textareaCls } from "@/components/ui";
import { addSource, askKnowledge, type AddState, type AskState } from "@/app/(app)/knowledge/actions";

const MODES = [
  { id: "file", label: "Upload files" },
  { id: "url", label: "Website address" },
  { id: "text", label: "Paste text" },
  { id: "faq", label: "Questions and answers" },
] as const;

export function AddKnowledge() {
  const [mode, setMode] = useState<(typeof MODES)[number]["id"]>("file");
  const [state, action, pending] = useActionState<AddState, FormData>(addSource, null);
  const form = useRef<HTMLFormElement>(null);
  const [fileName, setFileName] = useState("");

  useEffect(() => {
    if (state?.ok) {
      form.current?.reset();
      setFileName("");
    }
  }, [state]);

  return (
    <Card className="p-5 flex flex-col gap-5">
      <div>
        <h2 className="text-base font-semibold">Add knowledge</h2>
        <p className="text-[13px] text-ink-muted">Documents, web pages and spreadsheets your agent can answer from.</p>
      </div>
      <div className="inline-flex flex-wrap gap-1 p-1 rounded-[10px] bg-segmented w-fit" role="group" aria-label="How to add">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            aria-pressed={mode === m.id}
            onClick={() => setMode(m.id)}
            className={`h-9 px-3.5 rounded-[7px] text-sm ${mode === m.id ? "bg-card text-ink font-medium shadow-[var(--shadow-segment)]" : "text-ink-secondary"}`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <form ref={form} action={action} className="flex flex-col gap-4">
        <input type="hidden" name="mode" value={mode} />
        {mode === "file" && (
          <label className="flex flex-col items-center justify-center gap-2 text-center px-4 py-8 rounded-xl border border-dashed border-line-dashed cursor-pointer">
            <FileUp size={24} strokeWidth={1.75} aria-hidden />
            <span className="text-sm font-medium">{fileName || "Choose a file"}</span>
            <span className="text-[13px] text-ink-muted">PDF, Word, Excel, CSV or text. Up to 15 MB.</span>
            <input type="file" name="file" accept=".pdf,.docx,.xlsx,.csv,.txt,.md" className="sr-only" onChange={(e) => setFileName(e.target.files?.[0]?.name ?? "")} />
          </label>
        )}
        {mode === "url" && (
          <Field label="Web page address" helper="One page at a time. Pages that need a login or JavaScript may not be readable.">
            <input name="url" type="url" placeholder="https://yourbusiness.in/fees" className={inputCls} />
          </Field>
        )}
        {mode === "text" && (
          <Field label="Text" helper="Policies, timings, anything people ask about.">
            <textarea name="text" rows={7} className={textareaCls} />
          </Field>
        )}
        {mode === "faq" && (
          <Field label="Questions and answers" helper="Write each as Q: ... then A: ... This is the most accurate way to teach common questions.">
            <textarea name="text" rows={8} placeholder={"Q: Clinic kab khulta hai?\nA: Subah 9 se shaam 7 baje, Monday se Saturday.\n\nQ: Consultation fees kitni hai?\nA: Chhe sau rupaye."} className={textareaCls} />
          </Field>
        )}
        {mode !== "file" && (
          <Field label="Name (optional)">
            <input name="name" placeholder="For example: Fee policy" className={inputCls} />
          </Field>
        )}
        <div className="flex flex-wrap items-center gap-4">
          <Button disabled={pending}>{pending ? "Adding..." : "Add"}</Button>
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

// Re-reads the page while anything is still being processed, so statuses move without a manual refresh.
export function AutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [active, router]);
  return null;
}

export function SourceActions({ id, canRetry, onRetry, onDelete }: { id: string; canRetry: boolean; onRetry: (id: string) => Promise<void>; onDelete: (id: string) => Promise<void> }) {
  const [pending, start] = useTransition();
  return (
    <div className="flex gap-2">
      {canRetry && <Button variant="secondary" className="h-9" disabled={pending} onClick={() => start(() => onRetry(id))}>Try again</Button>}
      <Button
        variant="secondary"
        className="h-9"
        disabled={pending}
        onClick={() => {
          if (confirm("Delete this? Agents using it will stop answering from it.")) start(() => onDelete(id));
        }}
      >
        Delete
      </Button>
    </div>
  );
}

export function AskBox() {
  const [state, action, pending] = useActionState<AskState, FormData>(askKnowledge, null);
  return (
    <Card className="p-5 flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Check what it knows</h2>
        <p className="text-[13px] text-ink-muted">Ask a question the way a caller would. You will see the passages your agent would use.</p>
      </div>
      <form action={action} className="flex flex-wrap gap-3">
        <input name="question" required minLength={3} placeholder="Consultation ki fees kitni hai?" aria-label="Question" className={`${inputCls} flex-[1_1_240px]`} />
        <Button disabled={pending}>{pending ? "Searching..." : "Ask"}</Button>
      </form>
      <div aria-live="polite" className="flex flex-col gap-3">
        {state?.error && <p className="text-[13px] text-danger-fg">{state.error}</p>}
        {state && !state.error && state.passages.length === 0 && <p className="text-sm text-ink-muted">Nothing relevant was found. The agent would say it does not know.</p>}
        {state?.passages.map((p, i) => (
          <div key={i} className="rounded-lg bg-muted px-3.5 py-3 text-sm leading-[1.55]">
            <p>{p.content}</p>
            <span className="mt-2 inline-block px-2 py-[3px] rounded-sm border border-line text-xs text-ink-secondary bg-card">Source: {p.source}{p.section ? ` · ${p.section}` : ""}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
