"use server";

import { randomBytes } from "node:crypto";
import { AccessToken, RoomAgentDispatch, RoomConfiguration } from "livekit-server-sdk";
import { supabaseServer } from "@/lib/supabase/server";

// Issues a short-lived browser token for a test room. The room name carries the agent id and mode;
// the worker reads it to pick the config (apps/agent-worker/agent_worker/db.py parse_room).
export async function startTest(agentId: string, mode: "draft" | "live", callerNumber = ""): Promise<{ token: string; url: string } | { error: string }> {
  const supabase = await supabaseServer();
  const { data: user } = await supabase.auth.getUser();
  if (!user.user) return { error: "Please sign in again." };
  // Row-level security: this returns nothing unless the signed-in user's workspace owns the agent.
  const { data: agent } = await supabase.from("agents").select("id,published_version").eq("id", agentId).single();
  if (!agent) return { error: "Agent not found." };
  if (mode === "live" && !agent.published_version) return { error: "Publish a version first, or test the draft." };

  const url = process.env.LIVEKIT_URL;
  const key = process.env.LIVEKIT_API_KEY;
  const secret = process.env.LIVEKIT_API_SECRET;
  if (!url || !key || !secret) return { error: "Voice service is not configured." };

  const room = `${mode}-${agentId}-${randomBytes(3).toString("hex")}`;
  // Optional "pretend to call from" number: lets you test caller memory and callbacks without a phone line.
  const digits = callerNumber.replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "");
  const attributes: Record<string, string> = /^[6-9]\d{9}$/.test(digits) ? { caller_number: `+91${digits}` } : {};
  const at = new AccessToken(key, secret, { identity: `tester-${user.user.id.slice(0, 8)}`, ttl: "10m", attributes });
  at.addGrant({ roomJoin: true, room, canPublish: true, canSubscribe: true });
  // Ask for OUR worker by name, so no other app's agent on the same LiveKit project answers (D-060).
  at.roomConfig = new RoomConfiguration({ agents: [new RoomAgentDispatch({ agentName: process.env.AGENT_NAME || "voice-platform" })] });
  return { token: await at.toJwt(), url };
}
