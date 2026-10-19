import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { MobileTabBar, SideNav } from "@/components/nav";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await supabaseServer();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/login");
  return (
    <div className="min-h-screen flex flex-wrap bg-page">
      <SideNav email={data.user.email ?? ""} />
      <main className="flex-[999_1_640px] min-w-0 p-4 md:p-8 pb-24 md:pb-8 flex flex-col gap-6">{children}</main>
      <MobileTabBar />
    </div>
  );
}
