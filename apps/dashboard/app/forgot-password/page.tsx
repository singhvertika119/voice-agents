import Link from "next/link";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { siteUrl } from "@/lib/site-url";
import { Button, Field, inputCls } from "@/components/ui";
import { AuthShell, Notice, linkCls } from "@/components/auth-shell";
import { friendlyAuthError } from "@/lib/auth-messages";

async function sendReset(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "").trim();
  const supabase = await supabaseServer();
  const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${await siteUrl()}/auth/confirm?next=/reset-password` });
  // Same answer whether or not the email has an account, so the form cannot be used to find out who is registered.
  if (error && error.message.toLowerCase().includes("rate limit")) redirect(`/forgot-password?error=${encodeURIComponent(friendlyAuthError(error.message))}`);
  redirect("/login?notice=reset-sent");
}

export default async function ForgotPasswordPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <AuthShell title="Reset your password" intro="Enter your email and we will send a link to choose a new password.">
      <form action={sendReset} className="flex flex-col gap-5">
        <Field label="Email">
          <input name="email" type="email" required autoComplete="email" placeholder="you@business.in" className={inputCls} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button>Send reset link</Button>
        <Link href="/login" className={linkCls}>Back to sign in</Link>
      </form>
    </AuthShell>
  );
}
