import assert from "node:assert/strict";
import { test } from "node:test";
import { findPlaceholders } from "./agent-config.ts";
import { BUSINESS_TYPES, buildGreeting, buildInstructions, buildNotes, languageLine, templateConfig } from "./templates.ts";

const details = { name: "Sunrise Clinic", address: "Sector 62, Noida", hours: "Mon to Sat, 9 am to 7 pm", reasons: "timings, fees", languages: ["hinglish"] };

test("every template builds text with no [placeholders] the agent could read out", () => {
  for (const t of BUSINESS_TYPES) {
    const cfg = templateConfig(t);
    assert.deepEqual(findPlaceholders({ greeting: buildGreeting(details.name, details.languages), instructions: buildInstructions(t, details), knowledge: buildNotes(details) }), [], t.id);
    assert.deepEqual(findPlaceholders(cfg), [], `${t.id} starter config`);
  }
});

test("the greeting always says it is an AI assistant and that the call may be recorded", () => {
  assert.match(buildGreeting("X", ["hinglish"]), /AI assistant/);
  assert.match(buildGreeting("X", ["hinglish"]), /record/);
  assert.match(buildGreeting("X", ["english"]), /AI assistant.*recorded/);
});

test("the name is used exactly as typed", () => {
  assert.match(buildGreeting("Sunrise Clinic", ["hindi"]), /Sunrise Clinic/);
  assert.match(buildInstructions(BUSINESS_TYPES[0], details), /receptionist of Sunrise Clinic/);
});

test("notes contain only what the owner typed, empty answers are left out", () => {
  const n = buildNotes({ ...details, address: "", hours: "" });
  assert.equal(n, "Business name: Sunrise Clinic\nPeople usually call about: timings, fees");
  assert.ok(!n.includes("Address"));
});

test("language line follows the choices", () => {
  assert.equal(languageLine(["english"]), "Speak English.");
  assert.equal(languageLine(["hindi"]), "Speak Hindi.");
  assert.match(languageLine(["hindi", "english"]), /caller's language/);
});

test("business types carry safety rules, and the clinic one forbids medical advice", () => {
  const clinic = BUSINESS_TYPES.find((t) => t.id === "clinic")!;
  assert.match(buildInstructions(clinic, details), /Never give medical advice/);
  assert.match(buildInstructions(clinic, details), /112/);
  assert.match(buildInstructions(clinic, details), /Never invent prices, timings or names/);
  for (const t of BUSINESS_TYPES.filter((x) => x.id !== "scratch")) assert.ok(t.rules.length > 40, t.id);
});
