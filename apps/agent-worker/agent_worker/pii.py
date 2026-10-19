"""Remove identity numbers before anything is stored long-term or sent to a summarising model.

Aadhaar (12 digits with a valid Verhoeff check digit), PAN, payment cards (Luhn) and long bare account-like numbers
are replaced with a tag. Ordinary 10-digit phone numbers are NOT removed: callbacks need them, and they are
protected by retention and erasure instead (docs/decision.md D-052).
"""
from __future__ import annotations

import re

_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
      [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],
      [4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def verhoeff_ok(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def luhn_ok(number: str) -> bool:
    total, alt = 0, False
    for ch in reversed(number):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


# Digits separated by spaces or dashes, as speech-to-text writes them ("1234 5678 9012" or "1 2 3 4 ...").
_RUN = re.compile(r"(?<![\w+])\d(?:[ \-]?\d){8,18}(?!\w)")
_PAN = re.compile(r"\b[A-Za-z]{5}\s?\d{4}\s?[A-Za-z]\b")


def redact(text: str) -> str:
    def digits(m: re.Match) -> str:
        d = re.sub(r"\D", "", m.group(0))
        if len(d) == 12 and d[0] in "23456789" and verhoeff_ok(d):
            return "[AADHAAR]"
        if 13 <= len(d) <= 19 and luhn_ok(d):
            return "[CARD]"
        if len(d) >= 11:        # longer than a phone number: account-like
            return "[NUMBER]"
        return m.group(0)       # 9 or 10 digits: phone number, kept
    out = _RUN.sub(digits, text)
    return _PAN.sub("[PAN]", out)
