// Formats from docs/DESIGN.md section 8: Indian grouping, IST times.
const USD_TO_INR = 85; // TODO(design): replace with a live rate; used only to show cost in rupees.

export const inr = (usd: number | null | undefined) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format((usd ?? 0) * USD_TO_INR);

export const count = (n: number) => new Intl.NumberFormat("en-IN").format(n);

export const time = (d: string | Date) =>
  new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }).format(new Date(d));

export const duration = (s: number | null | undefined) => {
  if (!s) return "00:00";
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(Math.round(s % 60)).padStart(2, "0")}`;
};
