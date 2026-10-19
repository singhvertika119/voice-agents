"use server";

import { createClient } from "@supabase/supabase-js";
import { revalidatePath } from "next/cache";
import { supabaseServer } from "@/lib/supabase/server";

export type AddState = { ok: boolean; message: string; at: number } | null;
export type AskState = { question: string; passages: { section: string | null; content: string; source: string }[]; error?: string } | null;

const MAX_BYTES = 15_000_000;
const KINDS = ["pdf", "docx", "txt", "md", "csv", "xlsx"];

const fail = (message: string): AddState => ({ ok: false, message, at: Date.now() });
const done = (message: string): AddState => ({ ok: true, message, at: Date.now() });

async function member() {
  const supabase = await supabaseServer();
  const { data } = await supabase.from("tenant_members").select("tenant_id,role").limit(1).single();
  return { supabase, tenantId: data?.tenant_id as string | undefined, role: data?.role as string | undefined };
}

// One entry point for all four ways of adding knowledge. The source row is created as the signed-in user
// (so row-level security decides if they may), then the ingestion worker picks it up.
export async function addSource(_prev: AddState, formData: FormData): Promise<AddState> {
  const { supabase, tenantId, role } = await member();
  if (!tenantId || !["owner", "admin", "editor"].includes(role ?? "")) return fail("You do not have permission to add knowledge.");
  const mode = String(formData.get("mode"));
  const name = String(formData.get("name") ?? "").trim();
  let row: Record<string, unknown>;
  let file: File | null = null;

  if (mode === "text" || mode === "faq") {
    const text = String(formData.get("text") ?? "").trim();
    if (text.length < 10) return fail("Write or paste some content first.");
    if (text.length > 200_000) return fail("That is too long to paste. Upload it as a file instead.");
    row = { source_type: mode, raw_text: text, name: name || (mode === "faq" ? "Questions and answers" : "Notes") };
  } else if (mode === "url") {
    const url = String(formData.get("url") ?? "").trim();
    if (!/^https?:\/\/.+\..+/.test(url)) return fail("Enter a full web address, for example https://example.com/fees");
    row = { source_type: "url", url, name: name || new URL(url).hostname };
  } else if (mode === "file") {
    file = formData.get("file") as File | null;
    if (!file || file.size === 0) return fail("Choose a file to upload.");
    if (file.size > MAX_BYTES) return fail("That file is larger than 15 MB. Upload a smaller copy.");
    const kind = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!KINDS.includes(kind)) return fail("Use a PDF, Word (.docx), Excel (.xlsx), CSV or text file.");
    row = { source_type: "file", file_kind: kind, name: name || file.name };
  } else {
    return fail("Choose how to add knowledge.");
  }

  const { data: src, error } = await supabase
    .from("knowledge_sources")
    .insert({ ...row, tenant_id: tenantId, status: file ? "parsing" : "queued" }) // 'parsing' keeps the worker away until the upload lands
    .select("id")
    .single();
  if (error || !src) return fail("Could not add this. Please try again.");

  if (file) {
    // Storage writes use the service key on the server, only after the insert above proved membership.
    const admin = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
    const safe = file.name.replace(/[^\w.\-]+/g, "_");
    const path = `${tenantId}/${src.id}/${safe}`;
    const up = await admin.storage.from("knowledge").upload(path, Buffer.from(await file.arrayBuffer()), { contentType: file.type || undefined });
    if (up.error) {
      await supabase.from("knowledge_sources").update({ status: "failed", error: "The upload did not finish. Try again." }).eq("id", src.id);
      revalidatePath("/knowledge");
      return fail("The upload did not finish. Try again.");
    }
    await supabase.from("knowledge_sources").update({ storage_path: path, status: "queued" }).eq("id", src.id);
  }
  revalidatePath("/knowledge");
  return done("Added. It is being read now, which usually takes under a minute.");
}

export async function retrySource(id: string) {
  const supabase = await supabaseServer();
  await supabase.from("knowledge_sources").update({ status: "queued", error: null }).eq("id", id);
  revalidatePath("/knowledge");
}

export async function deleteSource(id: string) {
  const supabase = await supabaseServer();
  const { data: src } = await supabase.from("knowledge_sources").select("storage_path").eq("id", id).single();
  await supabase.from("knowledge_sources").delete().eq("id", id); // chunks and tables cascade
  if (src?.storage_path) {
    const admin = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
    await admin.storage.from("knowledge").remove([src.storage_path]);
  }
  revalidatePath("/knowledge");
}

// "Check what it knows": show the passages the agent would be given for a question.
export async function askKnowledge(_prev: AskState, formData: FormData): Promise<AskState> {
  const question = String(formData.get("question") ?? "").trim();
  if (question.length < 3) return null;
  const supabase = await supabaseServer();
  const { data: sources } = await supabase.from("knowledge_sources").select("id,name").in("status", ["ready"]);
  if (!sources?.length) return { question, passages: [], error: "Nothing is ready yet. Add knowledge and wait for it to finish." };
  try {
    const emb = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: "text-embedding-3-small", input: question }),
    });
    if (!emb.ok) throw new Error("embedding failed");
    const vec: number[] = (await emb.json()).data[0].embedding;
    const { data, error } = await supabase.rpc("match_chunks", {
      p_sources: sources.map((s) => s.id),
      p_embedding: `[${vec.join(",")}]`,
      p_query: question,
      p_k: 3,
    });
    if (error) throw error;
    const names = Object.fromEntries(sources.map((s) => [s.id, s.name]));
    return {
      question,
      passages: (data ?? []).map((r: { section: string | null; content: string; source_id: string }) => ({
        section: r.section, content: r.content, source: names[r.source_id] ?? "",
      })),
    };
  } catch {
    return { question, passages: [], error: "Could not search right now. Try again in a moment." };
  }
}
