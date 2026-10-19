import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { Button, Field, inputCls } from "@/components/ui";
import { Logo } from "@/components/nav";

async function authenticate(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const mode = String(formData.get("mode"));
  const supabase = await supabaseServer();
  const { error } =
    mode === "signup"
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password });
  if (error) redirect(`/login?error=${encodeURIComponent(error.message)}`);
  redirect("/");
}

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <main className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-[400px] flex flex-col gap-6">
        <Logo />
        <form action={authenticate} className="bg-card border border-line rounded-xl p-6 flex flex-col gap-5">
          <div>
            <h1 className="text-xl font-semibold">Sign in</h1>
            <p className="text-sm text-ink-muted mt-1">New here? Choose Create account with the same details.</p>
          </div>
          <Field label="Email">
            <input name="email" type="email" required autoComplete="email" placeholder="you@business.in" className={inputCls} />
          </Field>
          <Field label="Password" helper="At least 6 characters">
            <input name="password" type="password" required minLength={6} autoComplete="current-password" className={inputCls} />
          </Field>
          {error && <p role="alert" className="text-[13px] text-danger-fg">{error}</p>}
          <div className="flex flex-col gap-2">
            <Button name="mode" value="signin">Sign in</Button>
            <Button variant="secondary" name="mode" value="signup" formNoValidate={false}>Create account</Button>
          </div>
        </form>
      </div>
    </main>
  );
}
