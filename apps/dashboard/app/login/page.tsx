import Link from "next/link";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Button, Field, inputCls } from "@/components/ui";
import { AuthShell, Notice, linkCls } from "@/components/auth-shell";
import { friendlyAuthError } from "@/lib/auth-messages";

async function signIn(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const supabase = await supabaseServer();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) redirect(`/login?error=${encodeURIComponent(friendlyAuthError(error.message))}&email=${encodeURIComponent(email)}`);
  redirect("/");
}

const NOTICES: Record<string, string> = {
  confirmed: "Your email is confirmed. Sign in with the email and password you chose.",
  "password-reset": "Your password was changed. Sign in with the new one.",
  "reset-sent": "If that email has an account, a reset link is on its way. It can take a minute; check spam too.",
};

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string; notice?: string; email?: string }> }) {
  const { error, notice, email } = await searchParams;
  return (
    <AuthShell title="Sign in" intro="Welcome back.">
      <form action={signIn} className="flex flex-col gap-5">
        {notice && NOTICES[notice] && <Notice>{NOTICES[notice]}</Notice>}
        <Field label="Email">
          <input name="email" type="email" required autoComplete="email" defaultValue={email ?? ""} placeholder="you@business.in" className={inputCls} />
        </Field>
        <Field label="Password">
          <input name="password" type="password" required autoComplete="current-password" className={inputCls} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button>Sign in</Button>
        <div className="flex flex-wrap justify-between gap-x-4">
          <Link href="/forgot-password" className={linkCls}>Forgot password?</Link>
          <Link href="/signup" className={linkCls}>Create an account</Link>
        </div>
      </form>
    </AuthShell>
  );
}
