import { DEFAULT_CONFIG, type AgentConfig } from "./agent-config.ts";

// Starting points for the setup wizard. Wording follows the grounding rules in docs/decision.md D-063: the agent states
// only what the owner gave it, never gives advice the business cannot stand behind, and offers a callback instead of
// promising things (live transfer does not exist yet, D-051).
export type BusinessType = {
  id: string;
  label: string;
  blurb: string;
  role: string;       // "a clinic"
  rules: string;      // type-specific safety rules, plain sentences
  reasonsExample: string;
  tryThese: string[]; // sample caller lines for the test-call step
};

export const BUSINESS_TYPES: BusinessType[] = [
  {
    id: "clinic", label: "Clinic or diagnostic lab", blurb: "Timings, doctor availability, appointments, report status",
    role: "a clinic or diagnostic lab",
    rules: "Never give medical advice, diagnoses or medicine names. If the caller describes an emergency, tell them to call 112 or go to the nearest hospital straight away. For booking an appointment, offer a callback from the front desk unless a tool is available.",
    reasonsExample: "Doctor timings, appointment booking, consultation fees, report status",
    tryThese: ["What are your timings?", "Doctor kab available hain?", "Can I book an appointment?"],
  },
  {
    id: "coaching", label: "Coaching institute or school", blurb: "Fees, batch timings, admissions, results",
    role: "a coaching institute or school",
    rules: "Never promise admission, a seat, a discount or exam results. For admissions or counselling, offer a callback from the team.",
    reasonsExample: "Fee structure, batch timings, admission process, demo class",
    tryThese: ["Admission fees kitni hai?", "Batch timings kya hain?", "Can someone call me back about admission?"],
  },
  {
    id: "store", label: "Online store", blurb: "Order status, returns, refunds, delivery",
    role: "an online store",
    rules: "Share an order's status only from what a tool returns; never guess. Never promise a refund, replacement or delivery date. For returns and refunds, offer a callback from the support team.",
    reasonsExample: "Where is my order, return policy, refund timeline, delivery charges",
    tryThese: ["Mera order kab aayega?", "What is your return policy?", "I want a refund"],
  },
  {
    id: "realestate", label: "Real estate", blurb: "Project details, pricing, site visits",
    role: "a real estate developer",
    rules: "Never quote a price, discount or availability that is not in your information. For site visits and pricing discussions, offer a callback from the sales team.",
    reasonsExample: "Project location, configurations, site visit booking, price range",
    tryThese: ["Project kahan hai?", "Can I visit the site?", "What is the price range?"],
  },
  {
    id: "service", label: "Service business", blurb: "Bookings, rescheduling, service status",
    role: "a service business",
    rules: "Never promise a slot, a technician arrival time or a price that is not in your information. For bookings and rescheduling, offer a callback from the team unless a tool is available.",
    reasonsExample: "Booking a service, rescheduling, service charges, timings",
    tryThese: ["Mujhe service book karni hai", "What are your charges?", "Can I reschedule my visit?"],
  },
  {
    id: "scratch", label: "Start from scratch", blurb: "Write everything yourself",
    role: "a business",
    rules: "",
    reasonsExample: "The most common reasons people phone you",
    tryThese: ["What are your timings?", "How can I reach you?", "Can I talk to a person?"],
  },
];

export const LANGUAGES = [
  { id: "hindi", label: "Hindi" },
  { id: "english", label: "English" },
  { id: "hinglish", label: "Hinglish" },
] as const;

export type Details = {
  name: string;
  address: string;
  hours: string;
  reasons: string;
  languages: string[];
};

const BASE_RULES =
  "Reply in one or two short spoken sentences. Never use lists, markdown, symbols or URLs.\n" +
  "Answer only from the knowledge below. If it is not covered, say you do not have that information and offer to connect a human. " +
  "Never invent prices, timings or names.";

export function languageLine(languages: string[]): string {
  const set = new Set(languages);
  if (set.size === 1 && set.has("english")) return "Speak English.";
  if (set.size === 1 && set.has("hindi")) return "Speak Hindi.";
  return "Speak in the caller's language (Hindi, English or Hinglish).";
}

export function buildGreeting(name: string, languages: string[]): string {
  const english = languages.length === 1 && languages[0] === "english";
  return english
    ? `Hello, welcome to ${name}. I am an AI assistant and this call may be recorded. How can I help you?`
    : `Namaste, ${name} mein aapka swagat hai. Main ek AI assistant hoon aur yeh call record ho sakti hai. Main aapki kya madad kar sakti hoon?`;
}

export function buildInstructions(type: BusinessType, d: Pick<Details, "name" | "languages">): string {
  return [`You are the phone receptionist of ${d.name}, ${type.role}. ${languageLine(d.languages)}`, BASE_RULES, type.rules].filter(Boolean).join("\n");
}

// Only what the owner typed goes in. Empty answers are left out, never filled with a guess.
export function buildNotes(d: Details): string {
  return [
    `Business name: ${d.name}`,
    d.address && `Address: ${d.address}`,
    d.hours && `Timings: ${d.hours}`,
    d.reasons && `People usually call about: ${d.reasons}`,
  ].filter(Boolean).join("\n");
}

export function templateConfig(type: BusinessType): AgentConfig {
  const c = structuredClone(DEFAULT_CONFIG);
  c.instructions = buildInstructions(type, { name: "your business", languages: [] });
  c.knowledge = "";
  c.greeting = buildGreeting("your business", []);
  return c;
}

export const STEPS = [
  { id: "business-type", label: "Business type" },
  { id: "details", label: "Business details" },
  { id: "knowledge", label: "Knowledge" },
  { id: "voice", label: "Voice" },
  { id: "test-call", label: "Test call" },
] as const;
