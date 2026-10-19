"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { Mic, MicOff } from "lucide-react";
import { Room, RoomEvent, Track, type TranscriptionSegment, type Participant } from "livekit-client";
import { Button } from "@/components/ui";
import { startTest } from "@/app/(app)/agents/[id]/test-actions";

type Turn = { id: string; who: "agent" | "caller"; text: string };

// Talk to the agent from the browser. Uses the real worker, so it exercises the same voice, knowledge and
// fallbacks as a phone call.
export function TestPanel({ agentId, hasLive, hasDraft, placeholders = [] }: { agentId: string; hasLive: boolean; hasDraft: boolean; placeholders?: string[] }) {
  const [mode, setMode] = useState<"draft" | "live">(hasDraft ? "draft" : "live");
  const [state, setState] = useState<"idle" | "connecting" | "live">("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [muted, setMuted] = useState(false);
  const [fromNumber, setFromNumber] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const room = useRef<Room | null>(null);
  const audio = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      room.current?.disconnect();
    };
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [turns]);

  function connect() {
    setError(null);
    setTurns([]);
    setState("connecting");
    start(async () => {
      const res = await startTest(agentId, mode, fromNumber);
      if ("error" in res) {
        setError(res.error);
        setState("idle");
        return;
      }
      const r = new Room();
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) audio.current?.appendChild(track.attach());
      });
      r.on(RoomEvent.TranscriptionReceived, (segs: TranscriptionSegment[], p?: Participant) => {
        const who = p?.identity === r.localParticipant.identity ? "caller" : "agent";
        setTurns((prev) => {
          const next = [...prev];
          for (const s of segs) {
            const i = next.findIndex((t) => t.id === s.id);
            if (i >= 0) next[i] = { ...next[i], text: s.text };
            else next.push({ id: s.id, who, text: s.text });
          }
          return next;
        });
      });
      r.on(RoomEvent.Disconnected, () => setState("idle"));
      try {
        await r.connect(res.url, res.token);
        await r.localParticipant.setMicrophoneEnabled(true);
        room.current = r;
        setMuted(false);
        setState("live");
      } catch {
        setError("Could not start the call. Allow microphone access and try again.");
        setState("idle");
        r.disconnect();
      }
    });
  }

  function hangUp() {
    room.current?.disconnect();
    room.current = null;
    if (audio.current) audio.current.innerHTML = "";
    setState("idle");
  }

  async function toggleMute() {
    await room.current?.localParticipant.setMicrophoneEnabled(muted);
    setMuted(!muted);
  }

  return (
    <div className="bg-card border border-line rounded-xl flex flex-col">
      <div className="px-5 py-4 border-b border-line flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Test the agent</h2>
          <p className="text-[13px] text-ink-muted">Talk to it from your browser.</p>
        </div>
        {state === "live" && <span className="text-xs text-success-fg bg-success-bg px-2.5 py-[3px] rounded-full font-medium">On a call</span>}
      </div>

      {placeholders.length > 0 && (
        <p role="status" className="mx-5 mt-4 px-3 py-2 rounded-md bg-warning-bg text-warning-fg text-[13px]">
          Your latest save still has {placeholders.slice(0, 3).join(", ")}. The agent will say these out loud.
        </p>
      )}
      <div className="px-5 pt-4 flex gap-1 p-1" role="group" aria-label="Which version to test">
        <div className="inline-flex gap-1 p-1 rounded-[10px] bg-segmented">
          {([["draft", "Draft"], ["live", "Live version"]] as const).map(([id, label]) => (
            <button
              key={id}
              type="button"
              disabled={state !== "idle" || (id === "live" && !hasLive)}
              aria-pressed={mode === id}
              onClick={() => setMode(id)}
              className={`h-9 px-3.5 rounded-[7px] text-sm disabled:text-ink-faint ${mode === id ? "bg-card text-ink font-medium shadow-[var(--shadow-segment)]" : "text-ink-secondary"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="px-5 pt-4">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Pretend to call from (optional)
          <input
            value={fromNumber} onChange={(e) => setFromNumber(e.target.value)} disabled={state !== "idle"} inputMode="numeric" placeholder="98765 43210"
            className="h-11 px-3 rounded-md border border-line-strong bg-card text-sm font-mono font-normal"
          />
          <span className="text-[13px] text-ink-muted font-normal">Lets you test returning-caller memory and callbacks.</span>
        </label>
      </div>
      <div className="p-5 flex flex-col gap-3 min-h-[160px] max-h-[360px] overflow-y-auto" aria-live="polite">
        {turns.length === 0 && (
          <p className="text-sm text-ink-muted">
            {state === "live" ? "Say something, for example: What are your timings?" : "Start a call to hear your agent. Unsaved changes are not included, so save the draft first."}
          </p>
        )}
        {turns.map((t) => (
          <div key={t.id} className={`flex flex-col gap-1 ${t.who === "caller" ? "items-end" : ""}`}>
            <span className="text-xs font-medium text-ink-muted">{t.who === "caller" ? "You" : "Agent"}</span>
            <p className={`text-sm leading-[1.55] ${t.who === "caller" ? "px-3.5 py-2.5 rounded-lg bg-muted" : ""}`}>{t.text}</p>
          </div>
        ))}
        <div ref={end} />
      </div>

      {error && <p role="alert" className="px-5 pb-3 text-[13px] text-danger-fg">{error}</p>}

      <div className="px-5 py-4 border-t border-line flex items-center gap-3">
        {state === "live" ? (
          <>
            <button
              type="button"
              onClick={toggleMute}
              aria-label={muted ? "Unmute microphone" : "Mute microphone"}
              className="size-12 rounded-full bg-ink text-on-ink inline-flex items-center justify-center"
            >
              {muted ? <MicOff size={20} /> : <Mic size={20} />}
            </button>
            <Button variant="secondary" onClick={hangUp}>End call</Button>
          </>
        ) : (
          <Button onClick={connect} disabled={pending || state === "connecting"}>
            {state === "connecting" ? "Connecting..." : "Call from browser"}
          </Button>
        )}
      </div>
      <div ref={audio} className="hidden" aria-hidden />
    </div>
  );
}
