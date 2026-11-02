import type { Metadata } from "next";
import Link from "next/link";
import { Instrument_Serif, Noto_Sans_Devanagari } from "next/font/google";
import { Logo } from "@/components/nav";
import { ButtonLink } from "@/components/ui";
import { LandingCall } from "@/components/landing-call";

// Public landing page. Signed-out visitors to "/" see this (proxy.ts rewrites to /welcome); signed-in users get the
// dashboard as before. Static: no session or database reads, so it loads fast.
const instrument = Instrument_Serif({ subsets: ["latin"], weight: "400", style: "italic", variable: "--font-instrument" });
const deva = Noto_Sans_Devanagari({ subsets: ["devanagari", "latin"], weight: ["400", "500", "600"], variable: "--font-noto-deva" });

export const metadata: Metadata = {
  title: "Voice Agents · Your front desk, now fluent in Hinglish",
  description: "A phone receptionist that answers in Hindi, English or both, knows your business, and books a callback when a person is needed.",
};

const label = "block font-mono text-xs font-medium uppercase tracking-[0.08em] text-ink-faint";
const h2 = "text-[30px] md:text-[42px] leading-[1.08] font-semibold tracking-[-0.02em] text-balance";

function Pill({ tone, children }: { tone: "success" | "warning" | "neutral"; children: React.ReactNode }) {
  const cls = { success: "bg-success-bg text-success-fg", warning: "bg-warning-bg text-warning-fg", neutral: "bg-muted text-ink-secondary" }[tone];
  const dot = { success: "bg-success-dot", warning: "bg-warning-dot", neutral: "" }[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-xs font-medium whitespace-nowrap ${cls}`}>
      {dot && <span className={`size-1.5 rounded-full ${dot}`} aria-hidden />}
      {children}
    </span>
  );
}

function SectionHead({ kicker, title, intro }: { kicker: string; title: string; intro: string }) {
  return (
    <div className="grid md:grid-cols-2 gap-3.5 md:gap-10 md:items-end mb-8 md:mb-11">
      <div><span className={`${label} mb-3.5`}>{kicker}</span><h2 className={h2}>{title}</h2></div>
      <p className="text-ink-muted max-w-[34em]">{intro}</p>
    </div>
  );
}

const wrap = "max-w-[1120px] mx-auto px-4 sm:px-6";
const section = "py-14 md:py-[88px] border-t border-line";

const STEPS = [
  {
    n: "01", title: "Tell it who it works for",
    text: "Write the greeting and a few lines of instructions. The agent says your greeting exactly as you wrote it.",
    mini: (
      <>
        <span className="text-[11px] font-mono text-ink-faint">Greeting</span>
        <span className="bg-card border border-line-strong rounded-md px-2.5 py-1.5 text-ink-secondary">Namaste, Sunrise Clinic mein aapka swagat hai…</span>
        <span className="text-[11px] font-mono text-ink-faint">Voice</span>
        <span className="bg-card border border-line-strong rounded-md px-2.5 py-1.5 text-ink-secondary">Ritu · Hindi and English</span>
      </>
    ),
  },
  {
    n: "02", title: "Give it your knowledge",
    text: "Upload a PDF, a price list or your website. It answers from these and says so when something is not in them.",
    mini: (
      <>
        <div className="flex justify-between items-center gap-2 bg-card border border-line rounded-md px-2.5 py-1.5"><span>Fees and timings.pdf</span><Pill tone="success">Ready</Pill></div>
        <div className="flex justify-between items-center gap-2 bg-card border border-line rounded-md px-2.5 py-1.5"><span>sunriseclinic.in</span><Pill tone="neutral">Reading</Pill></div>
      </>
    ),
  },
  {
    n: "03", title: "Test it, then publish",
    text: "Call it from your browser, fix what you hear, and publish. Your changes stay a draft until you do.",
    mini: (
      <>
        <div className="flex justify-between items-center gap-2"><span>Version 4</span><Pill tone="warning">Draft</Pill></div>
        <div className="flex justify-between items-center gap-2"><span>Version 3</span><Pill tone="success">Live</Pill></div>
      </>
    ),
  },
];

const CALLS: { caller: string; want: string; length: string; outcome: [string, "success" | "warning" | "neutral"] }[] = [
  { caller: "+91 98XXX XX421", want: "Asked about Saturday timings for the dental clinic.", length: "1:12", outcome: ["Resolved", "success"] },
  { caller: "+91 70XXX XX108", want: "Wants a call back to book a full body checkup.", length: "2:05", outcome: ["Callback", "warning"] },
  { caller: "+91 99XXX XX736", want: "Billing complaint about an earlier visit.", length: "1:48", outcome: ["Handed off", "neutral"] },
  { caller: "+91 81XXX XX290", want: "Checked the consultation fee in Hindi.", length: "0:46", outcome: ["Resolved", "success"] },
];

const FAQ: [string, string][] = [
  ["Which languages does it speak?", "Hindi, English and Hinglish, including switching between them in the same call."],
  ["Do I need a developer?", "No. Everything is set up from the dashboard: greeting, instructions, documents and voice."],
  ["What if it cannot answer?", "It says it does not have that information and offers a callback from your team. It does not make things up."],
  ["Can it take calls on my phone number?", "Phone numbers are being connected now. Today you can build, test and talk to your agent from the browser."],
  ["Can I change it after it goes live?", "Yes. Edits are saved as a draft, and callers hear the new version only after you publish it."],
  ["Can I delete a caller's data?", "Yes. Settings has a delete option that removes a caller's calls, recordings and memory."],
];

export default function Welcome() {
  return (
    <div className={`${instrument.variable} ${deva.variable} min-h-screen bg-page`}>
      <header className="sticky top-0 z-10 bg-card border-b border-line">
        <div className={`${wrap} h-[60px] flex items-center justify-between gap-4`}>
          <Link href="/" aria-label="Voice Agents home" className="shrink-0 whitespace-nowrap"><Logo /></Link>
          <nav aria-label="Sections" className="hidden lg:flex gap-7 text-sm text-ink-muted whitespace-nowrap">
            <a href="#how" className="hover:text-ink">How it works</a>
            <a href="#features" className="hover:text-ink">What it does</a>
            <a href="#calls" className="hover:text-ink">Call log</a>
            <a href="#faq" className="hover:text-ink">Questions</a>
          </nav>
          <div className="flex gap-1 sm:gap-2 items-center shrink-0">
            {/* On a phone the bar keeps one button; "Sign in" is a plain link there. */}
            <span className="max-sm:hidden"><ButtonLink href="/login" variant="secondary" className="h-10 whitespace-nowrap">Sign in</ButtonLink></span>
            <Link href="/login" className="sm:hidden text-sm font-medium text-ink-secondary px-2 h-10 inline-flex items-center whitespace-nowrap">Sign in</Link>
            <ButtonLink href="/signup" className="h-10 px-3.5 sm:px-4 text-sm whitespace-nowrap"><span className="sm:hidden">Get started</span><span className="max-sm:hidden">Create your agent</span></ButtonLink>
          </div>
        </div>
      </header>

      <main>
        <div className={`${wrap} grid lg:grid-cols-[1.05fr_1fr] gap-10 lg:gap-14 items-center pt-12 pb-14 lg:pt-[72px] lg:pb-20`}>
          <div>
            <span className="inline-flex items-center gap-2 font-mono text-xs font-medium uppercase tracking-[0.08em] text-ink-muted border border-line bg-card px-2.5 py-1.5 rounded-full">
              <span className="size-[7px] rounded-full bg-success-dot" aria-hidden />For Indian businesses
            </span>
            <h1 className="mt-[22px] text-[40px] sm:text-[56px] lg:text-[68px] leading-[1.02] font-semibold tracking-[-0.02em] text-balance">
              Your front desk, now fluent in{" "}
              <em className="font-accent italic font-normal text-[1.12em] leading-[0.9] tracking-[-0.01em]">Hinglish.</em>
            </h1>
            <p className="mt-[22px] text-lg text-ink-muted max-w-[33em]">
              A phone receptionist that answers in Hindi, English or both, knows your business, and books a callback when a
              person is needed. No code. Set it up in an afternoon.
            </p>
            <div className="mt-[30px] grid grid-cols-1 sm:flex gap-2.5">
              <ButtonLink href="/signup" className="h-12">Create your agent</ButtonLink>
              <ButtonLink href="#how" variant="secondary" className="h-12 px-[22px] text-[15px]">See how it works</ButtonLink>
            </div>
            <p className="mt-4 text-[13px] text-ink-faint">Free to try. Test your agent in the browser before it takes a single call.</p>
          </div>
          <LandingCall />
        </div>

        <div className="py-7 border-t border-line">
          <div className={`${wrap} flex flex-wrap items-center gap-x-7 gap-y-2.5 text-[15px] text-ink-muted max-sm:gap-x-2`}>
            <span className={`${label} max-sm:w-full`}>Made for</span>
            {["Clinics", "Coaching institutes", "Online stores", "Real estate", "Service businesses"].map((x) => (
              <strong key={x} className="font-medium text-ink max-sm:text-sm max-sm:bg-card max-sm:border max-sm:border-line max-sm:rounded-full max-sm:px-3 max-sm:py-1">{x}</strong>
            ))}
          </div>
        </div>

        <section id="how" className={section}>
          <div className={wrap}>
            <SectionHead kicker="How it works" title="Three steps from blank page to answered calls."
              intro="You describe the business in plain words. The agent learns from the documents you already have. You talk to it yourself before anyone else does." />
            <div className="grid md:grid-cols-3 bg-card border border-line rounded-xl overflow-hidden divide-y md:divide-y-0 md:divide-x divide-line">
              {STEPS.map((s) => (
                <div key={s.n} className="p-7 flex flex-col gap-3.5">
                  <span className="font-mono text-[13px] font-medium text-ink-faint">{s.n}</span>
                  <h3 className="text-xl font-semibold tracking-[-0.01em]">{s.title}</h3>
                  <p className="text-[15px] text-ink-muted">{s.text}</p>
                  <div className="mt-auto border border-line rounded-[10px] p-3 bg-page text-[13px] flex flex-col gap-2">{s.mini}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="features" className={section}>
          <div className={wrap}>
            <SectionHead kicker="What it does" title="A front desk that never puts anyone on hold."
              intro="Built for how calls actually go in India: people switch languages mid-sentence, read out numbers, and ask for a person." />
            <div className="grid grid-cols-12 gap-4">
              <Feature span="col-span-12 md:col-span-7" title="Speaks the caller's language"
                text="It replies in whatever the caller just used, and switches when they do. Prices and dates are read in the same language as the rest of the sentence.">
                <div className="flex flex-wrap gap-2 mt-2">
                  {([["Hindi", <span key="h" className="font-deva">फीस पाँच सौ रुपये है।</span>], ["Hinglish", "Fees 500 rupaye hai."], ["English", "The fee is 500 rupees."]] as const).map(([k, v]) => (
                    <div key={k} className="flex-[1_1_150px] border border-line rounded-lg px-3 py-2.5 text-sm">
                      <small className="block font-mono text-[11px] font-medium uppercase tracking-wider text-ink-faint mb-0.5">{k}</small>{v}
                    </div>
                  ))}
                </div>
              </Feature>
              <Feature span="col-span-12 md:col-span-5" title="Answers only what it knows"
                text="It sticks to your documents. If a price or policy is not there, it says it does not have that information instead of guessing." />
              <Feature span="col-span-12 md:col-span-4" title="Books callbacks carefully"
                text="When a caller needs a person, it reads the number back digit by digit and books the callback only after a clear yes." />
              <Feature span="col-span-12 md:col-span-4" title="Remembers returning callers"
                text="A short summary of earlier calls is kept for each caller, so nobody has to explain twice." />
              <Feature span="col-span-12 md:col-span-4" title="Keeps personal numbers private"
                text="Aadhaar, PAN and card numbers are masked before anything is saved.">
                <div className="mt-1.5 font-mono text-[13px] bg-page border border-line rounded-lg px-3 py-2.5 text-ink-secondary">
                  Aadhaar <span className="bg-ink text-ink rounded-[3px]" aria-label="hidden digits">0000 0000</span> 4821
                </div>
              </Feature>
            </div>
          </div>
        </section>

        <section id="calls" className={section}>
          <div className={wrap}>
            <SectionHead kicker="Call log" title="Every call, written down."
              intro="Read the transcript, play the recording, and see what the caller wanted and how the call ended, without listening to all of it." />
            <ul className="sm:hidden flex flex-col bg-card border border-line rounded-xl divide-y divide-line">
              {CALLS.map((c) => (
                <li key={c.caller} className="p-4 flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-[13px] text-ink-muted tabular-nums">{c.caller}</span>
                    <Pill tone={c.outcome[1]}>{c.outcome[0]}</Pill>
                  </div>
                  <p className="text-sm text-ink-secondary">{c.want}</p>
                  <span className="font-mono text-xs text-ink-faint tabular-nums">{c.length} min</span>
                </li>
              ))}
            </ul>
            <div className="max-sm:hidden bg-card border border-line rounded-xl overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <thead>
                  <tr className="bg-muted text-xs text-ink-muted text-left">
                    {["Caller", "What they wanted", "Length", "Outcome"].map((h) => <th key={h} scope="col" className="font-medium px-4 py-2.5 border-b border-line">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {CALLS.map((c) => (
                    <tr key={c.caller} className="border-b border-line last:border-0">
                      <td className="px-4 py-3.5 font-mono text-[13px] text-ink-muted whitespace-nowrap tabular-nums">{c.caller}</td>
                      <td className="px-4 py-3.5 text-ink-secondary">{c.want}</td>
                      <td className="px-4 py-3.5 font-mono text-[13px] text-ink-muted tabular-nums">{c.length}</td>
                      <td className="px-4 py-3.5"><Pill tone={c.outcome[1]}>{c.outcome[0]}</Pill></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2.5 text-xs text-ink-faint">Example data.</p>
          </div>
        </section>

        <section id="faq" className={section}>
          <div className={wrap}>
            <SectionHead kicker="Questions" title="Before you start." intro="Short answers to what people ask first." />
            <div className="grid md:grid-cols-2 gap-x-12">
              {[FAQ.slice(0, 3), FAQ.slice(3)].map((col, ci) => (
                <div key={ci}>
                  {col.map(([q, a], i) => (
                    <details key={q} open={ci === 0 && i === 0} className="group border-b border-line py-[18px]">
                      <summary className="cursor-pointer list-none flex justify-between gap-4 font-medium [&::-webkit-details-marker]:hidden">
                        {q}<span className="font-mono text-ink-faint group-open:hidden" aria-hidden>+</span><span className="font-mono text-ink-faint hidden group-open:inline" aria-hidden>–</span>
                      </summary>
                      <p className="mt-2.5 text-[15px] text-ink-muted max-w-[36em]">{a}</p>
                    </details>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="pb-16 md:pb-[88px]">
          <div className={wrap}>
            <div className="bg-ink text-on-ink rounded-xl px-5 py-8 md:p-14 grid md:grid-cols-[1.4fr_1fr] gap-8 items-center">
              <div>
                <h2 className="text-[30px] md:text-[44px] leading-[1.06] font-semibold tracking-[-0.02em] text-balance">Your first agent takes an afternoon.</h2>
                <p className="mt-3 opacity-70">Write a greeting, upload what you know, and hear it answer.</p>
              </div>
              <div className="flex flex-wrap gap-2.5 md:justify-end">
                <Link href="/signup" className="inline-flex items-center h-12 px-[22px] rounded-lg bg-on-ink text-ink font-medium text-[15px] hover:opacity-90">Create your agent</Link>
                <Link href="/login" className="inline-flex items-center h-12 px-[22px] rounded-lg border border-on-ink/30 text-on-ink font-medium text-[15px] hover:bg-on-ink/10">Sign in</Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="pb-12">
        <div className={`${wrap} flex flex-wrap justify-between gap-4 text-[13px] text-ink-faint`}>
          <span>Voice Agents</span><span>Made in India for Indian businesses.</span>
        </div>
      </footer>
    </div>
  );
}

function Feature({ span, title, text, children }: { span: string; title: string; text: string; children?: React.ReactNode }) {
  return (
    <div className={`${span} bg-card border border-line rounded-xl p-[26px] flex flex-col gap-2.5`}>
      <h3 className="text-lg font-semibold tracking-[-0.01em]">{title}</h3>
      <p className="text-[15px] text-ink-muted">{text}</p>
      {children}
    </div>
  );
}
