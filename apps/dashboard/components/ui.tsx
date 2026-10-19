import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

// Primitives built from docs/DESIGN.md section 6. Tokens only.

const btnBase = "inline-flex items-center justify-center gap-2 rounded-lg font-medium";
const btnStyles = {
  primary: "h-11 px-[22px] bg-ink text-on-ink text-[15px] hover:bg-ink-secondary",
  secondary: "h-11 px-4 bg-card border border-line-strong text-ink text-sm hover:bg-muted",
  text: "h-11 px-2 text-ink-secondary text-[15px] hover:text-ink",
} as const;

export function Button({ variant = "primary", className = "", ...p }: ComponentProps<"button"> & { variant?: keyof typeof btnStyles }) {
  return <button {...p} className={`${btnBase} ${btnStyles[variant]} disabled:border-line disabled:text-ink-faint disabled:cursor-default ${className}`} />;
}

export function ButtonLink({ variant = "primary", className = "", ...p }: ComponentProps<typeof Link> & { variant?: keyof typeof btnStyles }) {
  return <Link {...p} className={`${btnBase} ${btnStyles[variant]} ${className}`} />;
}

const badge = {
  success: "bg-success-bg text-success-fg",
  warning: "bg-warning-bg text-warning-fg",
  danger: "bg-danger-bg text-danger-fg",
  neutral: "bg-muted text-ink-secondary",
} as const;

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof badge; children: ReactNode }) {
  return <span className={`px-2.5 py-[3px] rounded-full text-xs font-medium whitespace-nowrap ${badge[tone]}`}>{children}</span>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`bg-card border border-line rounded-xl ${className}`}>{children}</section>;
}

export function CardHeader({ title, caption, action }: { title: string; caption?: string; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-line">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        {caption && <p className="text-[13px] text-ink-muted">{caption}</p>}
      </div>
      {action}
    </div>
  );
}

export function MetricTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="bg-card border border-line rounded-xl px-5 py-[18px] flex flex-col gap-1.5">
      <span className="text-[13px] text-ink-muted">{label}</span>
      <span className="text-[28px] font-semibold tabular-nums leading-[1.2]">{value}</span>
      {note && <span className="text-xs text-ink-muted">{note}</span>}
    </div>
  );
}

export function Field({ label, helper, children }: { label: string; helper?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {helper && <span className="text-[13px] text-ink-muted">{helper}</span>}
    </label>
  );
}

export const inputCls = "h-11 px-3 rounded-md border border-line-strong bg-card text-[15px] text-ink w-full";
export const textareaCls = "px-3 py-2.5 rounded-md border border-line-strong bg-card text-[15px] leading-normal text-ink w-full resize-y";

export function EmptyState({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <Card className="p-6 flex flex-col items-start gap-4">
      <p className="text-sm leading-[1.55]">{text}</p>
      {action}
    </Card>
  );
}

export function PageHeader({ title, intro, action }: { title: string; intro?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.01em]">{title}</h1>
        {intro && <p className="text-[15px] text-ink-muted mt-1">{intro}</p>}
      </div>
      {action}
    </div>
  );
}
