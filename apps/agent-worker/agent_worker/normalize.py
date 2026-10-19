"""Make LLM text safe to speak: strip markup, expand money/abbreviations, space out digit strings."""
import re

_ABBREV = {r"\bDr\.?(?=\s)": "Doctor", r"\bMon\b": "Monday", r"\bTue\b": "Tuesday", r"\bWed\b": "Wednesday",
           r"\bThu\b": "Thursday", r"\bFri\b": "Friday", r"\bSat\b": "Saturday", r"\bSun\b": "Sunday"}


def _digits(m: re.Match) -> str:
    return " ".join(m.group(0))


def normalize_for_speech(text: str) -> str:
    t = re.sub(r"https?://\S+", "", text)
    t = re.sub(r"[*_#`>|~]+", "", t)                       # markdown
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)          # bullets
    t = re.sub(r"(?:₹|Rs\.?|INR)\s*([\d,]+)", lambda m: f"{m.group(1).replace(',', '')} rupees", t)
    for pat, rep in _ABBREV.items():
        t = re.sub(pat, rep, t)
    t = re.sub(r"\b\d{7,}\b", _digits, t)                  # phone / account numbers: digit by digit
    t = re.sub(r"\s+", " ", t)
    return t.strip()
