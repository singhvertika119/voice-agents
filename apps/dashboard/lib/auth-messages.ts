// Plain-English versions of the messages Supabase Auth returns.
export function friendlyAuthError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("invalid login credentials")) return "That email and password do not match. Check them and try again, or use Forgot password.";
  if (m.includes("email not confirmed")) return "This email is not confirmed yet. Open the confirmation email we sent and click the link, then sign in.";
  if (m.includes("rate limit")) return "Too many emails were sent just now. Please wait about an hour and try again.";
  if (m.includes("already registered")) return "This email already has an account. Sign in instead.";
  if (m.includes("password should be at least")) return "Choose a password with at least 6 characters.";
  if (m.includes("same password")) return "Choose a password different from your old one.";
  if (m.includes("expired") || m.includes("invalid")) return "That link has expired or was already used. Request a new one.";
  return message;
}
