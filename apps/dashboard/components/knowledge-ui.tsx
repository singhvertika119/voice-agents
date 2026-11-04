"use client";

import { type FormEvent, useActionState, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, FileUp } from "lucide-react";
import { Button, Card, Field, inputCls, textareaCls } from "@/components/ui";
import { addSource, chatKnowledge, type AddState, type ChatReply, type ChatTurn } from "@/app/(app)/knowledge/actions";

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
          <Field label="Website address" helper="Enter your home page to read the whole website (up to 40 pages, contact and FAQ pages first), or a deeper page to read just that part. Pages that need a login or JavaScript may not be readable.">
            <input name="url" type="url" placeholder="https://yourbusiness.in" className={inputCls} />
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

type ChatMessage = ChatTurn & { passages?: ChatReply["passages"]; error?: boolean };

// A small chatbot over the knowledge picked in the dropdown. The conversation lives in the browser only;
// each question sends the recent messages so follow-ups ("aur Sunday ko?") are understood.
export function AskBox({ sources }: { sources: { id: string; name: string }[] }) {
  const [sourceId, setSourceId] = useState("all");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [pending, start] = useTransition();
  const list = useRef<HTMLDivElement>(null);
  const chosen = sourceId === "all" || sources.some((s) => s.id === sourceId) ? sourceId : "all";

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages, pending]);

  function send(e: FormEvent) {
    e.preventDefault();
    const question = text.trim();
    if (question.length < 2 || pending) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: question }];
    setMessages(next);
    setText("");
    start(async () => {
      const history = next.filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
      const reply = await chatKnowledge(chosen, history);
      setMessages((m) => [...m, reply.error
        ? { role: "assistant", content: reply.error, error: true }
        : { role: "assistant", content: reply.answer, passages: reply.passages }]);
    });
  }

  return (
    <Card className="p-5 flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Ask your knowledge</h2>
        <p className="text-[13px] text-ink-muted">Pick what to ask about, then chat the way a caller would. Answers come only from what you picked.</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-[1_1_220px] min-w-0">
        <Field label="Ask about">
          <select
            value={chosen}
            onChange={(e) => { setSourceId(e.target.value); setMessages([]); }}
            className={`${inputCls} pr-8`}
            disabled={!sources.length}
          >
            <option value="all">All ready knowledge{sources.length ? ` (${sources.length})` : ""}</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
        </div>
        {messages.length > 0 && (
          <Button type="button" variant="secondary" className="h-11" disabled={pending} onClick={() => setMessages([])}>New chat</Button>
        )}
      </div>

      <div ref={list} aria-live="polite" className="flex flex-col gap-3 max-h-[440px] min-h-[120px] overflow-y-auto rounded-lg border border-line-subtle bg-page p-3">
        {!sources.length && <p className="text-sm text-ink-muted m-auto text-center">Nothing is ready yet. Add knowledge and wait for it to show Ready.</p>}
        {!!sources.length && !messages.length && (
          <p className="text-sm text-ink-muted m-auto text-center">Ask anything, for example &ldquo;Consultation ki fees kitni hai?&rdquo;</p>
        )}
        {messages.map((m, i) => (
          m.role === "user" ? (
            <p key={i} className="self-end max-w-[85%] rounded-2xl rounded-br-sm bg-ink text-on-ink px-3.5 py-2 text-sm leading-[1.5] whitespace-pre-wrap">{m.content}</p>
          ) : (
            <div key={i} className="self-start max-w-[92%] flex flex-col gap-1.5">
              <p className={`rounded-2xl rounded-bl-sm px-3.5 py-2 text-sm leading-[1.55] whitespace-pre-wrap ${m.error ? "bg-danger-bg text-danger-fg" : "bg-card border border-line"}`}>{m.content}</p>
              {!!m.passages?.length && (
                <details className="text-xs text-ink-secondary px-1">
                  <summary className="cursor-pointer">Where this came from ({m.passages.length})</summary>
                  <ul className="mt-2 flex flex-col gap-2">
                    {m.passages.map((p, j) => (
                      <li key={j} className="rounded-md bg-muted px-3 py-2 leading-[1.5]">
                        <span className="font-medium">{p.source}{p.section ? ` · ${p.section}` : ""}</span>
                        <p className="mt-1 line-clamp-4">{p.content}</p>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )
        ))}
        {pending && <p className="self-start rounded-2xl rounded-bl-sm bg-card border border-line px-3.5 py-2 text-sm text-ink-muted">Looking it up...</p>}
      </div>

      <form onSubmit={send} className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type a question"
          aria-label="Question"
          maxLength={1000}
          disabled={!sources.length}
          className={`${inputCls} flex-1 min-w-0`}
        />
        <Button disabled={pending || text.trim().length < 2 || !sources.length}>Send</Button>
      </form>
    </Card>
  );
}
