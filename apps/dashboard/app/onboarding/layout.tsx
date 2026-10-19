import { Suspense } from "react";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { StepRail } from "@/components/wizard";

export default async function OnboardingLayout({ children }: { children: React.ReactNode }) {
  const supabase = await supabaseServer();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/login");
  return (
    <div className="min-h-screen flex flex-wrap bg-page">
      <Suspense fallback={null}><StepRail /></Suspense>
      <main className="flex-[999_1_480px] min-w-0 px-4 py-8 md:px-12 md:py-10 flex flex-col gap-7">
        <div className="max-w-[960px] w-full flex flex-col gap-7 flex-1">{children}</div>
      </main>
    </div>
  );
}
