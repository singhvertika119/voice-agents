import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
AUDIO_DIR = ROOT / "data" / "audio"  # pairs of <name>.wav + <name>.txt (reference transcript)
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)


def key(name: str, required: bool = True) -> str | None:
    v = os.getenv(name)
    if required and not v:
        raise SystemExit(f"Missing {name} in .env")
    return v or None
