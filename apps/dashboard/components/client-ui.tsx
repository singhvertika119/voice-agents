"use client";

import { type RefObject, useEffect, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import type { ActionState } from "@/lib/action-state";

// Re-reads the page every few seconds while something is still being processed, so statuses move without a refresh.
export function AutoRefresh({ active, every = 3000 }: { active: boolean; every?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), every);
    return () => clearInterval(t);
  }, [active, every, router]);
  return null;
}

// A small secondary button that runs a server action, optionally after a confirm() question, and is disabled meanwhile.
export function ConfirmButton({ label, run, confirmText }: { label: string; run: () => Promise<void>; confirmText?: string }) {
  const [pending, start] = useTransition();
  return (
    <Button variant="secondary" className="h-9" disabled={pending} onClick={() => { if (!confirmText || confirm(confirmText)) start(() => run()); }}>
      {label}
    </Button>
  );
}

// Empties the form after it was saved successfully, so the next entry starts clean.
export function useResetOnOk(state: ActionState, form: RefObject<HTMLFormElement | null>, also?: () => void) {
  useEffect(() => {
    if (state?.ok) {
      form.current?.reset();
      also?.();
    }
  }, [state, form, also]);
}
