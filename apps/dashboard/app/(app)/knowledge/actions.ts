"use server";

import { createClient } from "@supabase/supabase-js";
import { revalidatePath } from "next/cache";
import { supabaseServer } from "@/lib/supabase/server";

export type AddState = { ok: boolean; message: string; at: number } | null;
type Passage = { section: string | null; content: string; source: string };

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

export type ChatTurn = { role: "user" | "assistant"; content: string };
export type ChatReply = { answer: string; passages: Passage[]; error?: string };

const CHAT_RULES = `You answer questions about a business using only the passages from its knowledge base given below.
- Use only facts in the passages. Never guess or add outside knowledge.
- If the passages do not contain the answer, say you could not find that in the selected knowledge, in one sentence.
- Reply in the language the user wrote in (English, Hindi or Hinglish).
- Be short and direct: a sentence or two, or a short list when they ask for several things.
- Earlier messages are there so you understand follow-up questions such as "and on Sunday?".
- If the question is vague (one or two words like "fees" or "tell me something") and the passages cover several different
  things it could mean, do not pick one. Ask which they mean, naming up to three options from the passages.
- Never end with an offer such as "Feel free to ask" or "Let me know if you need anything else".`;

// Same word list as the voice agent's small-talk check (agent_worker/knowledge.py), so both treat "okay" alike.
const SMALL_TALK = new Set(`ok okay okk haan han ha haa hmm hmmm ji ha-ji theek thik thikhai hai acha accha achha sahi
yes no nahi nope sure fine great cool nice good perfect awesome wow right hello hi hey helo bye goodbye alvida thanks thank you thankyou shukriya
dhanyavaad dhanyawad please sorry wait ruko main mein mai bas namaste got it understood samajh gaya gayi
ठीक है हाँ हां हा जी अच्छा सही नहीं ना हेलो हलो बाय धन्यवाद शुक्रिया नमस्ते ओके हम्म बस समझ गया गई`.split(/\s+/));
const GREETING = new Set("hello hi hey helo namaste हेलो हलो नमस्ते".split(" "));

// "hello", "okay", "thank you": no search (nothing to look up), and a short reply instead of a closing offer.
function smallTalk(text: string): "greeting" | "other" | null {
  const words = text.toLowerCase().match(/[\p{L}\p{M}\p{N}]+/gu) ?? [];
  if (!words.length || words.length > 4 || !words.every((w) => SMALL_TALK.has(w))) return null;
  return words.some((w) => GREETING.has(w)) ? "greeting" : "other";
}

// "Ask your knowledge": a chat that searches only the knowledge picked in the dashboard and answers from it.
// sourceId "all" means every ready item. The passages used are returned too, so people can see where an answer came from.
export async function chatKnowledge(sourceId: string, history: ChatTurn[]): Promise<ChatReply> {
  const turns = history.slice(-8).filter((t) => t.content.trim());
  const question = turns.at(-1)?.role === "user" ? turns.at(-1)!.content.trim().slice(0, 1000) : "";
  if (question.length < 2) return { answer: "", passages: [], error: "Type a question first." };
  const supabase = await supabaseServer();
  let q = supabase.from("knowledge_sources").select("id,name").eq("status", "ready");
  if (sourceId !== "all") q = q.eq("id", sourceId);
  const { data: sources } = await q;
  if (!sources?.length) {
    return { answer: "", passages: [], error: sourceId === "all" ? "Nothing is ready yet. Add knowledge and wait for it to finish." : "This item is not ready. Pick another one." };
  }
  const key = process.env.OPENAI_API_KEY;
  const headers = { Authorization: `Bearer ${key}`, "Content-Type": "application/json" };
  const chit = smallTalk(question);
  try {
    if (chit) {
      const hint = chit === "greeting"
        ? "The user only greeted you. Greet them back in a few words in their language and ask what they would like to know."
        : "The user only acknowledged, thanked you or said goodbye. Reply with one to five words in their language, such as \"Sure.\" or \"Theek hai.\". Do not offer more help.";
      const r = await fetch("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        headers,
        body: JSON.stringify({
          model: "gpt-4o-mini", temperature: 0.2, max_tokens: 40,
          messages: [{ role: "system", content: hint }, { role: "user", content: question }],
        }),
      });
      if (!r.ok) throw new Error("chat failed");
      return { answer: (await r.json()).choices?.[0]?.message?.content?.trim() || "Ji.", passages: [] };
    }
    // A short follow-up ("aur fees?") means little alone, so the previous question is searched with it.
    const prevUser = turns.slice(0, -1).filter((t) => t.role === "user").at(-1)?.content ?? "";
    const searchText = question.split(/\s+/).length < 6 && prevUser ? `${prevUser}\n${question}` : question;
    const emb = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST", headers, body: JSON.stringify({ model: "text-embedding-3-small", input: searchText }),
    });
    if (!emb.ok) throw new Error("embedding failed");
    const vec: number[] = (await emb.json()).data[0].embedding;
    const { data, error } = await supabase.rpc("match_chunks", {
      p_sources: sources.map((s) => s.id),
      p_embedding: `[${vec.join(",")}]`,
      p_query: question,
      p_k: 5,
    });
    if (error) throw error;
    const names = Object.fromEntries(sources.map((s) => [s.id, s.name]));
    const passages: Passage[] = (data ?? []).map((r: { section: string | null; content: string; source_id: string }) => ({
      section: r.section, content: r.content, source: names[r.source_id] ?? "",
    }));
    const context = passages.length
      ? passages.map((p, i) => `[${i + 1}] (${p.source}${p.section ? `, ${p.section}` : ""})\n${p.content}`).join("\n\n")
      : "(no passage matched)";
    const chat = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers,
      body: JSON.stringify({
        model: "gpt-4o-mini",
        temperature: 0.2,
        max_tokens: 400,
        messages: [
          { role: "system", content: CHAT_RULES },
          ...turns.slice(0, -1).map((t) => ({ role: t.role, content: t.content.slice(0, 2000) })),
          { role: "system", content: `Passages for the next question:\n${context}` },
          { role: "user", content: question },
        ],
      }),
    });
    if (!chat.ok) throw new Error("chat failed");
    const answer: string = (await chat.json()).choices?.[0]?.message?.content?.trim() ?? "";
    return { answer: answer || "I could not find that in the selected knowledge.", passages };
  } catch {
    return { answer: "", passages: [], error: "Could not answer right now. Try again in a moment." };
  }
}
