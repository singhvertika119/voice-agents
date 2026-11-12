import { createClient } from "@supabase/supabase-js";

// The service-role client. It bypasses row-level security, so server code may use it only after checking, with the
// user's own session, that the user belongs to the workspace it is about to touch. Never import this into client code.
export function adminClient() {
  return createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
}
