"use client";

import { useEffect } from "react";
import { Button, Card } from "@/components/ui";

// Shown inside the dashboard frame (navigation stays) when a page fails to load, instead of the browser's crash page.
// In production Next hides the real message; error.digest matches the line in the server log.
export default function DashboardError({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  const digest = error instanceof Error && "digest" in error ? String((error as Error & { digest?: string }).digest ?? "") : "";
  return (
    <Card className="p-6 flex flex-col items-start gap-4 max-w-xl">
      <div>
        <h1 className="text-xl font-semibold">This page could not load</h1>
        <p className="text-sm text-ink-muted mt-1 leading-[1.55]">
          Something went wrong on our side. Try again; if it keeps happening, the problem is noted in the server log
          {digest ? <> with reference <span className="font-mono">{digest}</span></> : null}.
        </p>
      </div>
      <Button onClick={() => retry()}>Try again</Button>
    </Card>
  );
}
