import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { MobileTabBar, SideNav } from "@/components/nav";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await supabaseServer();
  // getClaims checks the signed session locally when it can; getUser would add a round trip to Supabase on every page.
  // The proxy has already refreshed the session, and every query is still protected by row-level security.
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims) redirect("/login");
  return (
    <div className="min-h-screen flex flex-wrap bg-page">
      <SideNav email={typeof data.claims.email === "string" ? data.claims.email : ""} />
      <main className="flex-[999_1_640px] min-w-0 p-4 md:p-8 pb-24 md:pb-8 flex flex-col gap-6">{children}</main>
      <MobileTabBar />
    </div>
  );
}
