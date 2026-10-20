import Link from "next/link";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { siteUrl } from "@/lib/site-url";
import { Button, Field, inputCls } from "@/components/ui";
import { AuthShell, Notice, linkCls } from "@/components/auth-shell";
import { friendlyAuthError } from "@/lib/auth-messages";

async function signUp(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const supabase = await supabaseServer();
  const { data, error } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: `${await siteUrl()}/auth/confirm` } });
  if (error) redirect(`/signup?error=${encodeURIComponent(friendlyAuthError(error.message))}&email=${encodeURIComponent(email)}`);
  // With email confirmation on there is no session yet: tell them to check their inbox.
  if (!data.session) redirect(`/signup?sent=${encodeURIComponent(email)}`);
  redirect("/");
}

export default async function SignupPage({ searchParams }: { searchParams: Promise<{ error?: string; email?: string; sent?: string }> }) {
  const { error, email, sent } = await searchParams;
  if (sent) {
    return (
      <AuthShell title="Check your email" intro={`We sent a confirmation link to ${sent}.`}>
        <ol className="list-decimal pl-5 text-sm text-ink flex flex-col gap-1.5">
          <li>Open the email (look in spam if you do not see it within a minute).</li>
          <li>Click the link in it. You will be signed in and taken to setup.</li>
          <li>If the link opens somewhere that does not sign you in, just sign in with the email and password you chose here.</li>
        </ol>
        <Link href="/login" className={linkCls}>Go to sign in</Link>
      </AuthShell>
    );
  }
  return (
    <AuthShell title="Create your account" intro="You will get an email to confirm your address.">
      <form action={signUp} className="flex flex-col gap-5">
        <Field label="Email">
          <input name="email" type="email" required autoComplete="email" defaultValue={email ?? ""} placeholder="you@business.in" className={inputCls} />
        </Field>
        <Field label="Password" helper="At least 6 characters">
          <input name="password" type="password" required minLength={6} autoComplete="new-password" className={inputCls} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button>Create account</Button>
        <Link href="/login" className={linkCls}>Already have an account? Sign in</Link>
      </form>
    </AuthShell>
  );
}
