"use server";

import { revalidatePath } from "next/cache";
import { supabaseServer } from "@/lib/supabase/server";

export async function setCallbackStatus(id: string, status: "done" | "cancelled" | "open") {
  const supabase = await supabaseServer();
  await supabase.from("callbacks").update({ status }).eq("id", id);
  revalidatePath("/callbacks");
}
