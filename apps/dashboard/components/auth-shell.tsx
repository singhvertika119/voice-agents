import type { ReactNode } from "react";
import { Logo } from "@/components/nav";

export function AuthShell({ title, intro, children }: { title: string; intro?: string; children: ReactNode }) {
  return (
    <main className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-[400px] flex flex-col gap-6">
        <Logo />
        <div className="bg-card border border-line rounded-xl p-6 flex flex-col gap-5">
          <div>
            <h1 className="text-xl font-semibold">{title}</h1>
            {intro && <p className="text-sm text-ink-muted mt-1">{intro}</p>}
          </div>
          {children}
        </div>
      </div>
    </main>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error"; children: ReactNode }) {
  return (
    <p role={tone === "error" ? "alert" : "status"} className={`text-[13px] rounded-md px-3 py-2.5 ${tone === "error" ? "bg-danger-bg text-danger-fg" : "bg-subtle text-ink"}`}>
      {children}
    </p>
  );
}

export const linkCls = "text-sm font-medium underline underline-offset-2 inline-flex items-center min-h-11";
