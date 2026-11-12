// Formats from docs/DESIGN.md section 8: Indian grouping, IST times.
const USD_TO_INR = 85; // TODO(design): replace with a live rate; used only to show cost in rupees.

export const inr = (usd: number | null | undefined) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format((usd ?? 0) * USD_TO_INR);

export const count = (n: number) => new Intl.NumberFormat("en-IN").format(n);

export const time = (d: string | Date) =>
  new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }).format(new Date(d));

type Tone = "neutral" | "success" | "warning" | "danger";

// How a call ended, for the calls list and the call page.
export const OUTCOME: Record<string, { tone: Tone; label: string }> = {
  resolved: { tone: "success", label: "Resolved" },
  handed_off: { tone: "warning", label: "Handed off" },
  dropped: { tone: "danger", label: "Dropped" },
  callback: { tone: "neutral", label: "Callback booked" },
};

// Where a knowledge item is in the reading pipeline, for the Knowledge page and the setup wizard.
export const KNOWLEDGE_STATUS: Record<string, { tone: Tone; label: string }> = {
  queued: { tone: "neutral", label: "Waiting" },
  parsing: { tone: "neutral", label: "Reading" },
  indexing: { tone: "neutral", label: "Indexing" },
  testing: { tone: "neutral", label: "Checking" },
  ready: { tone: "success", label: "Ready" },
  needs_review: { tone: "warning", label: "Needs review" },
  failed: { tone: "danger", label: "Failed" },
};
export const KNOWLEDGE_BUSY = ["queued", "parsing", "indexing", "testing"];

export const duration = (s: number | null | undefined) => {
  if (!s) return "00:00";
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(Math.round(s % 60)).padStart(2, "0")}`;
};
