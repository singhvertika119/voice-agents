import { NextResponse, type NextRequest } from "next/server";
import type { EmailOtpType } from "@supabase/supabase-js";
import { supabaseServer } from "@/lib/supabase/server";

// Where the links in Supabase's emails land. Handles both link styles:
// ?code=... (default templates) and ?token_hash=...&type=... (custom templates, work in any browser).
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const code = searchParams.get("code");
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const next = searchParams.get("next");
  const dest = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  const supabase = await supabaseServer();

  let ok = false;
  if (code) ok = !(await supabase.auth.exchangeCodeForSession(code)).error;
  else if (tokenHash && type) ok = !(await supabase.auth.verifyOtp({ type, token_hash: tokenHash })).error;

  if (ok) return NextResponse.redirect(new URL(dest, request.url));
  // Opened in a different browser than the one that signed up, or the link was used already.
  const fallback = dest === "/reset-password" ? "/reset-password" : "/login?notice=confirmed";
  return NextResponse.redirect(new URL(fallback, request.url));
}
