// Shape of agent_versions.config. Mirrors agents/*.yaml read by the worker (apps/agent-worker/agent_worker/config.py).
export type AgentConfig = {
  language: string;
  greeting: string;
  instructions: string;
  knowledge: string;            // free-text notes added to the prompt
  knowledge_sources?: string[]; // ids of uploaded sources (knowledge_sources.id), pinned per version
  tool_ids?: string[];          // custom tools (tools.id) this agent may use, pinned per version
  wizard?: { type: string; details?: { name: string; address: string; hours: string; reasons: string; languages: string[] } }; // setup wizard answers, ignored by the worker
  voice: { tts_primary: Record<string, string>; tts_fallback: Record<string, string> };
  stt: { primary: Record<string, string>; fallback: Record<string, string> };
  llm: Record<string, unknown>;
  turn_detection: string;
};

// Voices offered to non-technical users: plain names, mapped to provider settings.
export const VOICES = [
  { id: "ritu", label: "Ritu", note: "Warm, female" },
  { id: "priya", label: "Priya", note: "Clear, female" },
  { id: "aditya", label: "Aditya", note: "Calm, male" },
  { id: "rahul", label: "Rahul", note: "Friendly, male" },
] as const;

export const DEFAULT_CONFIG: AgentConfig = {
  language: "hi-IN",
  greeting:
    "Namaste, [Your clinic name] mein aapka swagat hai. Main ek AI assistant hoon aur yeh call record ho sakti hai. Main aapki kya madad kar sakti hoon?",
  instructions:
    "You are the phone receptionist of [Your business name]. Speak in the caller's language (Hindi, English or Hinglish).\nReply in one or two short spoken sentences. Never use lists, markdown, symbols or URLs.\nAnswer only from the knowledge below. If it is not covered, say you do not have that information and offer to connect a human. Never invent prices, timings or names.",
  knowledge: "[Timings]\n[Prices]\n[Common questions and answers]",
  voice: {
    tts_primary: { provider: "sarvam", model: "bulbul:v3", speaker: "ritu" },
    tts_fallback: { provider: "cartesia", model: "sonic-3" },
  },
  stt: {
    primary: { provider: "sarvam", model: "saaras:v3", mode: "codemix" },
    fallback: { provider: "deepgram", model: "nova-3" },
  },
  llm: {
    primary: { provider: "openai", model: "gpt-4o-mini" },
    fallback: { provider: "groq", model: "openai/gpt-oss-20b", reasoning_effort: "low" },
    fallback2: { provider: "gemini", model: "gemini-2.5-flash" },
    max_tokens: 200,
  },
  turn_detection: "multilingual",
};

// Text in [square brackets] is a template placeholder the owner must replace before the agent goes live.
export function findPlaceholders(cfg: Pick<AgentConfig, "greeting" | "instructions" | "knowledge">): string[] {
  const found = new Set<string>();
  for (const text of [cfg.greeting, cfg.instructions, cfg.knowledge]) {
    for (const m of text.matchAll(/\[[^\]\n]{2,60}\]/g)) found.add(m[0]);
  }
  return [...found];
}
