import { Check } from "lucide-react";
import { Button } from "@/components/ui";
import { BUSINESS_TYPES } from "@/lib/templates";
import { startFromTemplate } from "../actions";

export default async function BusinessTypeStep({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <form action={startFromTemplate} className="flex flex-col gap-7 flex-1">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">What kind of business do you run?</h1>
        <p className="text-[15px] text-ink-muted mt-2">We will start your agent with sensible rules for it. You can change everything later.</p>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4" role="radiogroup" aria-label="Kind of business">
        {BUSINESS_TYPES.map((t) => (
          <label
            key={t.id}
            className={`relative rounded-xl p-5 flex flex-col gap-2.5 text-left cursor-pointer has-[:checked]:border-2 has-[:checked]:border-ink ${
              t.id === "scratch" ? "border border-dashed border-line-dashed bg-transparent" : "bg-card border border-line"
            }`}
          >
            <input type="radio" name="type" value={t.id} required className="peer sr-only" />
            <span className="absolute top-3 right-3 size-5 rounded-full bg-ink text-on-ink hidden peer-checked:inline-flex items-center justify-center" aria-hidden>
              <Check size={12} strokeWidth={2.5} />
            </span>
            <span className="text-[15px] font-semibold">{t.label}</span>
            <span className="text-[13px] text-ink-muted">{t.blurb}</span>
          </label>
        ))}
      </div>
      {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}
      <div className="mt-auto pt-5 border-t border-line flex items-center justify-between">
        <span />
        <Button>Continue</Button>
      </div>
    </form>
  );
}
