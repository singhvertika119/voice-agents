"use client";

import { useEffect, useRef, useState } from "react";
import { Phone } from "lucide-react";

// The example call in the landing page hero: every turn is readable at rest; the highlight and the wave only show who
// is speaking. With reduced motion the wave is drawn once and nothing moves.
const TURNS: { who: "agent" | "caller"; text: React.ReactNode; length: number }[] = [
  { who: "agent", text: "Namaste, Sunrise Clinic mein aapka swagat hai. Main aapki kya madad kar sakti hoon?", length: 84 },
  { who: "caller", text: <>Kal Dr. Mehta available hain? <span className="font-deva">मुझे checkup करवाना है।</span></>, length: 52 },
  { who: "agent", text: "Haan, Dr. Mehta kal subah 10 se 1 baje tak available hain.", length: 58 },
  { who: "caller", text: "Okay, can someone call me back to fix the time?", length: 47 },
  { who: "agent", text: "Of course. I have 98 XXX XXX 21. Is that the right number?", length: 58 },
];

export function LandingCall() {
  const [active, setActive] = useState(-1);
  const canvas = useRef<HTMLCanvasElement>(null);
  const speaking = useRef(0);
  const activeRef = useRef(-1);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--color-ink").trim() || "#18181b";
    const faint = css.getPropertyValue("--color-line-strong").trim() || "#d4d4d8";

    const size = () => {
      const r = el.getBoundingClientRect(), d = window.devicePixelRatio || 1;
      el.width = Math.max(1, r.width * d); el.height = Math.max(1, r.height * d);
      ctx.setTransform(d, 0, 0, d, 0, 0);
    };
    let frame = 0;
    const draw = (now: number) => {
      const w = el.clientWidth, h = el.clientHeight, bars = Math.floor(w / 6), mid = h / 2;
      ctx.clearRect(0, 0, w, h);
      const i0 = activeRef.current;
      const isCaller = i0 >= 0 && TURNS[i0].who === "caller";
      for (let i = 0; i < bars; i++) {
        const p = i / bars, env = Math.sin(Math.PI * p);
        const amp = reduce ? 0.25 + 0.5 * Math.abs(Math.sin(i * 0.7)) * env
          : speaking.current * env * (0.35 + 0.65 * Math.abs(Math.sin(i * 0.9 + now / 160) * Math.cos(i * 0.31 - now / 420)));
        const bh = Math.max(2, amp * (h - 16));
        ctx.fillStyle = speaking.current > 0.05 && (isCaller ? p > 0.5 : p <= 0.5) ? ink : faint;
        ctx.fillRect(i * 6 + 2, mid - bh / 2, 2, bh);
      }
      if (!reduce) frame = requestAnimationFrame(draw);
    };

    size();
    window.addEventListener("resize", size);
    if (reduce) {
      draw(0);
      return () => window.removeEventListener("resize", size);
    }
    const timers: number[] = [];
    const step = (i: number) => {
      activeRef.current = i;
      setActive(i);
      const dur = Math.min(5200, 1400 + TURNS[i].length * 38);
      speaking.current = 1;
      timers.push(window.setTimeout(() => { speaking.current = 0.04; }, dur - 500));
      timers.push(window.setTimeout(() => step((i + 1) % TURNS.length), dur));
    };
    step(0);
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      timers.forEach(clearTimeout);
      window.removeEventListener("resize", size);
    };
  }, []);

  return (
    <figure className="m-0 bg-card border border-line rounded-xl overflow-hidden" aria-label="Example call between a caller and an agent">
      <div className="flex items-center justify-between gap-3 px-4 py-3.5 border-b border-line">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="size-[34px] rounded-full bg-muted text-ink-secondary inline-flex items-center justify-center shrink-0" aria-hidden>
            <Phone size={16} strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold truncate">Sunrise Clinic<span className="max-[380px]:hidden"> · Front desk</span></div>
            <div className="text-xs text-ink-faint font-mono">Example call · Hinglish</div>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-xs font-medium bg-success-bg text-success-fg whitespace-nowrap">
          <span className="size-1.5 rounded-full bg-success-dot animate-pulse" aria-hidden />On call
        </span>
      </div>
      <canvas ref={canvas} className="block w-full h-14 border-b border-line" aria-hidden />
      <ol className="list-none m-0 p-4 flex flex-col gap-2.5">
        {TURNS.map((t, i) => (
          <li key={i} className={`flex flex-col gap-1 max-w-[94%] sm:max-w-[86%] transition-opacity duration-300 ${t.who === "caller" ? "self-end items-end" : ""} ${active === -1 || active === i ? "opacity-100" : "opacity-45"}`}>
            <span className="font-mono text-[11px] font-medium uppercase tracking-wider text-ink-faint">{t.who === "agent" ? "Agent" : "Caller"}</span>
            <span className={`px-3 py-2.5 rounded-[10px] text-sm leading-normal border ${t.who === "caller" ? "bg-muted" : "bg-card"} ${active === i ? "border-ink-faint" : t.who === "caller" ? "border-transparent" : "border-line"}`}>
              {t.text}
            </span>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2 items-center justify-between px-4 py-3 border-t border-line bg-muted text-xs text-ink-muted">
        <div className="flex gap-3.5 flex-wrap font-mono"><span>Hindi ⇄ English</span><span>Answered from your documents</span></div>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-xs font-medium bg-warning-bg text-warning-fg whitespace-nowrap">
          <span className="size-1.5 rounded-full bg-warning-dot" aria-hidden />Callback booked
        </span>
      </div>
    </figure>
  );
}
