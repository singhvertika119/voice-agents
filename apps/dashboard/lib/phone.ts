// Same rules as the agent worker's normalize_phone: a leading + (or 00) means international and is kept;
// otherwise only an Indian mobile number is accepted. Returns E.164 or null.
export function toE164(raw: string): string | null {
  const text = raw.trim();
  let digits = text.replace(/\D/g, "");
  if (text.startsWith("+") || text.startsWith("00")) {
    if (text.startsWith("00")) digits = digits.slice(2);
    if (digits.startsWith("91")) return /^91\d{10}$/.test(digits) ? `+${digits}` : null;
    return /^[1-9]\d{7,14}$/.test(digits) ? `+${digits}` : null;
  }
  digits = digits.replace(/^91(?=\d{10}$)/, "").replace(/^0(?=\d{10}$)/, "");
  return /^[6-9]\d{9}$/.test(digits) ? `+91${digits}` : null;
}
