import { supabaseServer } from "@/lib/supabase/server";

// Who may do what. Row-level security enforces the same rules in the database; these checks exist so the person
// gets a clear message instead of a silent "nothing happened".
export type Role = "owner" | "admin" | "editor" | "viewer";
export const EDITORS: readonly Role[] = ["owner", "admin", "editor"];
export const ADMINS: readonly Role[] = ["owner", "admin"];

export const canEdit = (role?: string | null) => EDITORS.includes(role as Role);
export const isAdmin = (role?: string | null) => ADMINS.includes(role as Role);

// The signed-in user's workspace and role (one workspace per user today). tenantId is undefined when signed out.
export async function currentMember(tenantId?: string) {
  const supabase = await supabaseServer();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return { supabase, tenantId: undefined, role: undefined };
  let q = supabase.from("tenant_members").select("tenant_id,role").eq("user_id", user.id);
  if (tenantId) q = q.eq("tenant_id", tenantId);
  const { data } = await q.limit(1).maybeSingle();
  return { supabase, tenantId: data?.tenant_id as string | undefined, role: data?.role as Role | undefined };
}
