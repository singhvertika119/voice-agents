"""Writes deploy/.env.agent: only the keys the voice agent needs on LiveKit Cloud, copied from .env.

    uv run python scripts/make_agent_secrets.py

LiveKit supplies LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET itself. The file is ignored by git (.env.*) and by the
LiveKit upload; delete it after `lk agent create` has read it.
"""
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
NEEDED = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
          "SARVAM_API_KEY", "DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "TOOL_SECRET_KEY"]
env = dotenv_values(ROOT / ".env")
missing = [k for k in NEEDED if not env.get(k)]
if missing:
    raise SystemExit(f"Missing in .env: {', '.join(missing)}")
out = ROOT / "deploy" / ".env.agent"
out.write_text("".join(f"{k}={env[k]}\n" for k in NEEDED), encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)} with {len(NEEDED)} keys:", ", ".join(NEEDED))
