"""Voice-oriented normalisation and structure-aware chunking."""
from __future__ import annotations

import re
from dataclasses import dataclass

from vp_core.text import spoken_rupees

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
    # Protect emails and STD-coded phone numbers so markdown and citation cleanup do not mangle them
    emails: list[str] = []
    def _save_email(m: re.Match) -> str:
        emails.append(m.group(0))
        return f"QQQEMAIL{len(emails) - 1}QQQ"

    phones: list[str] = []
    def _save_phone(m: re.Match) -> str:
        phones.append(m.group(0))
        return f"QQQPHONE{len(phones) - 1}QQQ"

    # Match emails first
    t = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", _save_email, text)
    # Match STD phone patterns like (022) 2345 6789 or (0141) 2345678
    t = re.sub(r"\(\s*0\d{1,4}\s*\)\s*[\d\s-]{6,12}\d", _save_phone, t)

    # Rewrite markdown images and links before stripping raw URLs
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)                     # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                 # links -> label text
    t = re.sub(r"https?://\S+|www\.\S+", "", t)                     # raw URLs cannot be spoken

    # Citations: [1], [12], (1), (12) (never 0-prefixed area codes)
    t = re.sub(r"\[\d{1,3}\]|\(\s*[1-9]\d{0,1}\s*\)(?=\s|$)", "", t)
    t = re.sub(r"[*_`]{1,3}", "", t)                               # markdown emphasis
    t = re.sub(r"[→←↗›»«]+", " ", t)                                 # decorative arrows from web buttons
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)                 # bullets

    # Restore protected emails and phone numbers
    for i, em in enumerate(emails):
        t = t.replace(f"QQQEMAIL{i}QQQ", em)
    for i, ph in enumerate(phones):
        t = t.replace(f"QQQPHONE{i}QQQ", ph)

    t = spoken_rupees(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _sections(md: str) -> list[tuple[str, str]]:
    """Split on headings; returns (section path like 'Fees > ECG', body)."""
    path: list[tuple[int, str]] = []
    cur: list[str] = []
    out: list[tuple[str, str]] = []
    all_headings: list[tuple[str, str]] = []

    def flush():
        body = "\n".join(cur).strip()
        label = " > ".join(h for _, h in path)
        if body:
            out.append((label, body))
        cur.clear()

    for line in md.split("\n"):
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, m.group(2)))
            all_headings.append((" > ".join(h for _, h in path), m.group(2)))
        else:
            cur.append(line)
    flush()

    if not out and all_headings:
        # A document made only of headings yields valid chunks instead of nothing
        out.extend(all_headings)

    return out


def _split_body(body: str) -> list[str]:
    """Pack paragraphs into ~TARGET_CHARS pieces; split overlong paragraphs on newlines, sentences or words."""
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= TARGET_CHARS:
            pieces.append(para)
        else:
            # Overlong paragraph: try splitting on single newlines first (menus, addresses, tables)
            lines = [l.strip() for l in para.split("\n") if l.strip()]
            for line in lines:
                if len(line) <= TARGET_CHARS:
                    pieces.append(line)
                else:
                    # Still too long: split on sentence ends
                    sents = re.split(r"(?<=[.!?।])\s+", line)
                    cur = ""
                    for sent in sents:
                        sent = sent.strip()
                        if not sent:
                            continue
                        if len(sent) > TARGET_CHARS:
                            if cur:
                                pieces.append(cur)
                                cur = ""
                            # Sentence itself exceeds TARGET_CHARS: split on words
                            words = sent.split()
                            sub = ""
                            for w in words:
                                if len(sub) + len(w) + 1 > TARGET_CHARS:
                                    if sub:
                                        pieces.append(sub)
                                    sub = w
                                else:
                                    sub = f"{sub} {w}".strip()
                            if sub:
                                cur = sub
                        elif cur and len(cur) + len(sent) + 1 > TARGET_CHARS:
                            pieces.append(cur)
                            cur = sent
                        else:
                            cur = f"{cur} {sent}".strip()
                    if cur:
                        pieces.append(cur)
    packed: list[str] = []
    for p in pieces:
        if packed and len(packed[-1]) + len(p) + 1 < TARGET_CHARS:
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
