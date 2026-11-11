import { createCipheriv, createDecipheriv, createHmac, randomBytes } from "node:crypto";
import { lookup } from "node:dns/promises";
import net from "node:net";

function secretKey(): Buffer {
  const raw = process.env.TOOL_SECRET_KEY;
  if (!raw) throw new Error("TOOL_SECRET_KEY is not set");
  const key = Buffer.from(raw, "base64");
  if (key.length !== 32) throw new Error("TOOL_SECRET_KEY must be 32 bytes, base64 encoded");
  return key;
}

// Same layout as packages/core/vp_core/secrets.py: base64(iv[12] + ciphertext + tag[16]), AES-256-GCM.
export function encryptSecret(plain: string): string {
  const key = secretKey();
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", key, iv);
  const enc = Buffer.concat([c.update(plain, "utf8"), c.final()]);
  return Buffer.concat([iv, enc, c.getAuthTag()]).toString("base64");
}

export function decryptSecret(token: string): string {
  const buf = Buffer.from(token, "base64");
  const d = createDecipheriv("aes-256-gcm", secretKey(), buf.subarray(0, 12));
  d.setAuthTag(buf.subarray(buf.length - 16));
  return Buffer.concat([d.update(buf.subarray(12, buf.length - 16)), d.final()]).toString("utf8");
}

export function sign(secret: string, timestamp: string, body: string): string {
  return createHmac("sha256", secret).update(`${timestamp}.${body}`).digest("hex");
}

function privateIp(ip: string): boolean {
  if (net.isIPv6(ip)) {
    const l = ip.toLowerCase();
    return l === "::1" || l === "::" || l.startsWith("fe80") || l.startsWith("fc") || l.startsWith("fd") || l.startsWith("::ffff:127.") || l.startsWith("::ffff:10.") || l.startsWith("::ffff:192.168.");
  }
  const [a, b] = ip.split(".").map(Number);
  return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || a >= 224 || (a === 100 && b >= 64 && b <= 127);
}

// Public https addresses only; every address the name resolves to must be public.
export async function assertPublicHttps(url: string): Promise<string | null> {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return "Enter a full web address starting with https://";
  }
  if (u.protocol !== "https:") return "Use an https:// address.";
  try {
    const addrs = await lookup(u.hostname, { all: true });
    if (addrs.some((a) => privateIp(a.address))) return "That address is not a public website, so it cannot be used.";
  } catch {
    return "That web address could not be found. Check the spelling.";
  }
  return null;
}
