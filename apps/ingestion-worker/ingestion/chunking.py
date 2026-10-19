"""Voice-oriented normalisation and structure-aware chunking."""
from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 900     # roughly 200-300 tokens: small enough to read aloud, large enough to hold one idea
MAX_CHARS = 1400


@dataclass
class Chunk:
    idx: int
    section: str
    content: str  # section path + text, ready to embed and to inject into a prompt

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)


def estimate_tokens(text: str) -> int:
    # Devanagari costs roughly twice the tokens per character of English; this errs on the high side.
    deva = len(re.findall(r"[ऀ-ॿ]", text))
    return int((len(text) - deva) / 4 + deva / 1.6) + 1


def normalize_for_voice(text: str) -> str:
    t = re.sub(r"https?://\S+|www\.\S+", "", text)                 # URLs cannot be spoken
    t = re.sub(r"\[\d{1,3}\]|\(\s*\d{1,3}\s*\)(?=\s|$)", "", t)    # [1] citation markers
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)                     # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                 # links -> text
    t = re.sub(r"[*_`]{1,3}", "", t)
    t = re.sub(r"[→←↗›»«]+", " ", t)                                 # decorative arrows from web buttons
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)                 # bullets
    t = re.sub(r"(?:₹|Rs\.?|INR)\s*([\d,]+)", lambda m: f"{m.group(1).replace(',', '')} rupees", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _sections(md: str) -> list[tuple[str, str]]:
    """Split on headings; returns (section path like 'Fees > ECG', body)."""
    path: list[tuple[int, str]] = []
    cur: list[str] = []
    out: list[tuple[str, str]] = []

    def flush():
        body = "\n".join(cur).strip()
        if body:
            out.append((" > ".join(h for _, h in path), body))
        cur.clear()

    for line in md.split("\n"):
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, m.group(2)))
        else:
            cur.append(line)
    flush()
    return out


def _split_body(body: str) -> list[str]:
    """Pack paragraphs into ~TARGET_CHARS pieces; split overlong paragraphs on sentence ends."""
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= MAX_CHARS:
            pieces.append(para)
        else:
            cur = ""
            for sent in re.split(r"(?<=[.!?।])\s+", para):
                if cur and len(cur) + len(sent) > TARGET_CHARS:
                    pieces.append(cur.strip())
                    cur = ""
                cur += sent + " "
            if cur.strip():
                pieces.append(cur.strip())
    packed: list[str] = []
    for p in pieces:
        if packed and len(packed[-1]) + len(p) < TARGET_CHARS:
            packed[-1] += "\n" + p
        else:
            packed.append(p)
    return packed


def chunk_markdown(md: str, doc_title: str = "") -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, body in _sections(normalize_for_voice(md)):
        label = section or doc_title
        for piece in _split_body(body):
            text = f"{label}: {piece}" if label else piece
            chunks.append(Chunk(idx=len(chunks), section=label, content=text))
    return chunks
