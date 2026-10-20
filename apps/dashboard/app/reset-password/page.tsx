import Link from "next/link";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Button, Field, inputCls } from "@/components/ui";
import { AuthShell, Notice, linkCls } from "@/components/auth-shell";
import { friendlyAuthError } from "@/lib/auth-messages";

async function setPassword(formData: FormData) {
  "use server";
  const password = String(formData.get("password") ?? "");
  const again = String(formData.get("again") ?? "");
  if (password !== again) redirect(`/reset-password?error=${encodeURIComponent("The two passwords are not the same.")}`);
  const supabase = await supabaseServer();
  const { error } = await supabase.auth.updateUser({ password });
  if (error) redirect(`/reset-password?error=${encodeURIComponent(friendlyAuthError(error.message))}`);
  await supabase.auth.signOut();
  redirect("/login?notice=password-reset");
}

// Reached from the email link, which signs the person in for this one purpose (see /auth/confirm).
export default async function ResetPasswordPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const supabase = await supabaseServer();
  const { data } = await supabase.auth.getUser();
  if (!data.user) {
    return (
      <AuthShell title="This link has expired" intro="Reset links work once and for a short time.">
        <Link href="/forgot-password" className={linkCls}>Send me a new link</Link>
      </AuthShell>
    );
  }
  return (
    <AuthShell title="Choose a new password" intro={`For ${data.user.email}.`}>
      <form action={setPassword} className="flex flex-col gap-5">
        <Field label="New password" helper="At least 6 characters">
          <input name="password" type="password" required minLength={6} autoComplete="new-password" className={inputCls} />
        </Field>
        <Field label="New password again">
          <input name="again" type="password" required minLength={6} autoComplete="new-password" className={inputCls} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button>Change password</Button>
      </form>
    </AuthShell>
  );
}
