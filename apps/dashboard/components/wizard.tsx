"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { Check, Play } from "lucide-react";
import { Logo } from "@/components/nav";
import { Button, inputCls } from "@/components/ui";
import { STEPS } from "@/lib/templates";
import { VOICES } from "@/lib/agent-config";
import { previewVoice } from "@/app/onboarding/actions";

export function StepRail() {
  const path = usePathname();
  const agent = useSearchParams().get("agent") ?? undefined;
  const current = Math.max(0, STEPS.findIndex((s) => path.endsWith(s.id)));
  return (
    <aside className="flex-[1_1_240px] max-w-[300px] bg-card border-r border-line px-6 py-8 flex flex-col gap-8">
      <Logo />
      <nav aria-label="Setup steps">
        <ol className="flex flex-col gap-1">
          {STEPS.map((s, i) => {
            const done = i < current;
            const isCurrent = i === current;
            const body = (
              <>
                <span
                  className={`size-6 shrink-0 rounded-full inline-flex items-center justify-center text-xs font-medium ${
                    done ? "bg-ink text-on-ink" : isCurrent ? "border-2 border-ink" : "border border-line-strong text-ink-faint"
                  }`}
                >
                  {done ? <Check size={12} strokeWidth={2.5} aria-hidden /> : i + 1}
                </span>
                <span className={done ? "text-ink-muted" : isCurrent ? "font-medium" : "text-ink-faint"}>{s.label}</span>
              </>
            );
            return (
              <li key={s.id} aria-current={isCurrent ? "step" : undefined} className={`rounded-md ${isCurrent ? "bg-muted" : ""}`}>
                {done && agent ? (
                  <Link href={`/onboarding/${s.id}?agent=${agent}`} className="flex items-center gap-3 px-3 py-2.5 text-sm">{body}</Link>
                ) : (
                  <span className="flex items-center gap-3 px-3 py-2.5 text-sm">{body}</span>
                )}
              </li>
            );
          })}
        </ol>
      </nav>
      <p className="mt-auto text-[13px] text-ink-muted">Setup takes about 15 minutes.</p>
    </aside>
  );
}

export function WizardFooter({ backHref, primary, pending }: { backHref?: string; primary: string; pending?: boolean }) {
  return (
    <div className="mt-auto pt-5 border-t border-line flex items-center justify-between gap-4">
      {backHref ? <Link href={backHref} className="h-11 px-2 inline-flex items-center text-[15px] font-medium text-ink-secondary hover:text-ink">Back</Link> : <span />}
      <Button disabled={pending}>{primary}</Button>
    </div>
  );
}

// Plays a short synthesis of the given text in the given voice. Shows plain messages when it cannot.
export function PlayButton({ voice, text, label = "Play" }: { voice: string; text: string | (() => string); label?: string }) {
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  return (
    <span className="inline-flex flex-col gap-1">
      <button
        type="button"
        disabled={pending}
        aria-label={`${label} (${voice})`}
        onClick={() =>
          start(async () => {
            setMsg(null);
            const res = await previewVoice(voice, typeof text === "function" ? text() : text);
            if ("error" in res) return setMsg(res.error);
            audio.current?.pause();
            audio.current = new Audio(res.audio);
            void audio.current.play().catch(() => setMsg("Your browser blocked the sound. Click again."));
          })
        }
        className="h-10 px-3.5 rounded-lg bg-card border border-line-strong text-sm font-medium inline-flex items-center gap-2 hover:bg-muted disabled:text-ink-faint"
      >
        <Play size={14} strokeWidth={2} aria-hidden /> {pending ? "Loading..." : label}
      </button>
      {msg && <span role="alert" className="text-[13px] text-danger-fg">{msg}</span>}
    </span>
  );
}

export function VoiceStep({ initial }: { initial: string }) {
  const [sentence, setSentence] = useState("Namaste, aapka appointment kal shaam paanch baje hai. Fees chhe sau rupaye hai.");
  const [chosen, setChosen] = useState(initial);
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4" role="radiogroup" aria-label="Voice">
        {VOICES.map((v) => {
          const selected = chosen === v.id;
          return (
            <div key={v.id} className={`relative bg-card rounded-xl p-5 flex flex-col gap-3 ${selected ? "border-2 border-ink" : "border border-line"}`}>
              <label className="flex flex-col gap-1 cursor-pointer">
                <input type="radio" name="voice" value={v.id} checked={selected} onChange={() => setChosen(v.id)} className="sr-only" />
                {selected && (
                  <span className="absolute top-3 right-3 size-5 rounded-full bg-ink text-on-ink inline-flex items-center justify-center" aria-hidden>
                    <Check size={12} strokeWidth={2.5} />
                  </span>
                )}
                <span className="text-[15px] font-semibold">{v.label}</span>
                <span className="text-[13px] text-ink-muted">{v.note}</span>
              </label>
              <PlayButton voice={v.id} text={sentence} label="Hear it" />
            </div>
          );
        })}
      </div>
      <label className="flex flex-col gap-1.5 max-w-[640px]">
        <span className="text-sm font-medium">Try your own sentence</span>
        <input value={sentence} onChange={(e) => setSentence(e.target.value)} maxLength={220} className={inputCls} />
        <span className="text-[13px] text-ink-muted">Then press Hear it on any voice.</span>
      </label>
    </div>
  );
}
