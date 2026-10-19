"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { Card, CardHeader } from "@/components/ui";

export type Turn = { seq: number; speaker: string; text: string; at_ms: number | null; latency_ms: number | null };

const BARS = 60;
const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// A turn is saved when it ENDS, so jump a little before its time: about 0.4 s per word, plus a short lead-in.
const seekTime = (t: Turn) => Math.max(0, (t.at_ms ?? 0) / 1000 - t.text.split(/\s+/).length * 0.4 - 0.3);

function AudioPlayer({ url, seconds, audioRef }: { url: string; seconds: number; audioRef: React.RefObject<HTMLAudioElement | null> }) {
  const [playing, setPlaying] = useState(false);
  const [now, setNow] = useState(0);
  const [duration, setDuration] = useState(seconds);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [failed, setFailed] = useState(false);

  // Draw the waveform from the real audio. If the browser cannot decode it, flat bars are shown and playback still works.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const buf = await (await fetch(url)).arrayBuffer();
        const ctx = new AudioContext();
        const audio = await ctx.decodeAudioData(buf);
        void ctx.close();
        const left = audio.getChannelData(0);
        const right = audio.numberOfChannels > 1 ? audio.getChannelData(1) : left;
        const step = Math.floor(left.length / BARS) || 1;
        const raw = Array.from({ length: BARS }, (_, i) => {
          let max = 0;
          for (let j = i * step; j < Math.min(left.length, (i + 1) * step); j += 16) max = Math.max(max, Math.abs(left[j]), Math.abs(right[j]));
          return max;
        });
        const top = Math.max(...raw, 0.01);
        if (!cancelled) setPeaks(raw.map((p) => Math.max(0.08, p / top)));
      } catch {
        if (!cancelled) setPeaks(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url]);

  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) void a.play().catch(() => setFailed(true));
    else a.pause();
  }, [audioRef]);

  const seekFraction = (f: number) => {
    const a = audioRef.current;
    if (a && duration) a.currentTime = Math.min(duration, Math.max(0, f * duration));
  };

  const progress = duration ? now / duration : 0;
  return (
    <Card className="px-5 py-4 flex items-center gap-4">
      <audio
        ref={audioRef}
        src={url}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setDuration(e.currentTarget.duration)}
        onError={() => setFailed(true)}
      />
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? "Pause recording" : "Play recording"}
        className="size-11 shrink-0 rounded-full bg-ink text-on-ink inline-flex items-center justify-center hover:bg-ink-secondary"
      >
        {playing ? <Pause size={18} strokeWidth={2} /> : <Play size={18} strokeWidth={2} className="ml-0.5" />}
      </button>
      <div
        className="flex-1 h-10 flex items-center gap-[3px] cursor-pointer"
        role="slider"
        tabIndex={0}
        aria-label="Position in the recording"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(now)}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          seekFraction((e.clientX - r.left) / r.width);
        }}
        onKeyDown={(e) => {
          const a = audioRef.current;
          if (!a) return;
          if (e.key === "ArrowRight") a.currentTime = Math.min(duration, a.currentTime + 5);
          if (e.key === "ArrowLeft") a.currentTime = Math.max(0, a.currentTime - 5);
          if (e.key === " " || e.key === "Enter") {
            e.preventDefault();
            toggle();
          }
        }}
      >
        {Array.from({ length: BARS }, (_, i) => (
          <span
            key={i}
            aria-hidden
            className={`flex-1 rounded-full ${i / BARS < progress ? "bg-ink-secondary" : "bg-line-strong"}`}
            style={{ height: `${Math.round((peaks?.[i] ?? 0.2) * 100)}%`, minWidth: 2 }}
          />
        ))}
      </div>
      <span className="font-mono text-[13px] tabular-nums text-ink-secondary whitespace-nowrap">{mmss(now)} / {mmss(duration)}</span>
      {failed && <span role="alert" className="text-[13px] text-danger-fg basis-full">The recording could not play. Reload the page; the link expires after a few minutes.</span>}
    </Card>
  );
}

export function CallReview({ turns, audioUrl, seconds }: { turns: Turn[]; audioUrl: string | null; seconds: number }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const seek = (t: Turn) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = seekTime(t);
    void a.play().catch(() => {});
  };
  return (
    <div className="flex-[999_1_480px] min-w-0 flex flex-col gap-4">
      {audioUrl && <AudioPlayer url={audioUrl} seconds={seconds} audioRef={audioRef} />}
      <Card>
        <CardHeader title="Transcript" caption={audioUrl ? "Select a time to hear that part." : undefined} />
        <div className="p-5 flex flex-col gap-4" aria-live="polite">
          {!turns.length && <p className="text-sm text-ink-muted">No transcript was saved for this call.</p>}
          {turns.map((t) => (
            <div key={t.seq} className="flex gap-3">
              {audioUrl ? (
                <button type="button" onClick={() => seek(t)} aria-label={`Play from ${mmss(seekTime(t))}`} className="w-11 shrink-0 text-left font-mono text-xs text-ink-secondary pt-1 hover:text-ink underline-offset-2 hover:underline">
                  {mmss((t.at_ms ?? 0) / 1000)}
                </button>
              ) : (
                <span className="w-11 shrink-0 font-mono text-xs text-ink-muted pt-1">{mmss((t.at_ms ?? 0) / 1000)}</span>
              )}
              <div className={`flex-1 flex flex-col gap-1 ${t.speaker === "caller" ? "items-end" : ""}`}>
                <span className="text-xs font-medium text-ink-muted">{t.speaker === "caller" ? "Caller" : "Agent"}</span>
                <p className={`text-sm leading-[1.55] ${t.speaker === "caller" ? "px-3.5 py-2.5 rounded-lg bg-muted" : ""}`}>{t.text}</p>
                {t.speaker === "agent" && t.latency_ms != null && (
                  <span className="px-2 py-[3px] rounded-sm border border-line text-xs text-ink-secondary font-mono w-fit">{(t.latency_ms / 1000).toFixed(1)} s</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
