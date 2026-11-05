"""Where a reply is cut into pieces for the voice, so the first audio starts sooner (D-115).

The voice could only start once a whole first sentence had been written: our own number clean-up waited for the
sentence end, then the Sarvam plugin's sentence splitter waited again. A reply such as "Ji, hamara head office
Jaipur mein hai, E-42 Reyansh Tower..." had to finish its first sentence before anything was spoken.

Now each reply may be cut once early, at the first comma, semicolon or colon followed by a space, once the
piece is at least FIRST_CLAUSE_MIN characters long. After that, cuts are at sentence ends only (".", "!", "?",
"।"), so the voice does not pause at every comma. A comma inside a number ("1,20,000") has no space after it,
so numbers are never cut.
"""
from __future__ import annotations

import re

from livekit.agents import tokenize
from livekit.agents.tokenize import token_stream

FIRST_CLAUSE_MIN = 25   # characters before the first early cut: shorter pieces sound choppy
SENTENCE_MIN = 20       # same minimum as LiveKit's own sentence splitter
_END = re.compile(r"(?<=[.!?।॥])[\"”')\]]*\s+")
_CLAUSE = re.compile(r"(?<=[,;:])\s+")


class ClauseSplitter:
    """Cuts the text of one reply. Keep one per reply: it remembers whether the early cut was used."""

    def __init__(self) -> None:
        self.first_sent = False   # once the reply's first piece has gone, cut at sentence ends only

    def __call__(self, text: str) -> list[tuple[str, int, int]]:
        cuts: list[tuple[int, int, bool]] = [(m.start(), m.end(), False) for m in _END.finditer(text)]
        if not self.first_sent:
            cuts += [(m.start(), m.end(), True) for m in _CLAUSE.finditer(text)]
        cuts.sort()
        out: list[tuple[str, int, int]] = []
        start = 0
        early = False
        for cut_start, cut_end, is_clause in cuts:
            piece = text[start:cut_start].strip()
            if is_clause and (early or out or len(piece) < FIRST_CLAUSE_MIN):
                continue    # only one early cut, and only for the reply's first piece
            if len(piece) < SENTENCE_MIN:
                continue    # too short ("Ji.", "Rs."): keep it with what follows
            out.append((piece, start, cut_end))
            early = early or is_clause
            start = cut_end
        rest = text[start:].strip()
        if rest:
            out.append((rest, start, len(text)))
        # The caller sends every piece but the last at once, so with two or more pieces the first one is now spoken.
        if len(out) > 1:
            self.first_sent = True
        return out


class ClauseTokenizer(tokenize.SentenceTokenizer):
    """Drop-in for the Sarvam plugin's sentence splitter. The plugin opens one stream per reply."""

    def tokenize(self, text: str, *, language: str | None = None) -> list[str]:
        return [p for p, _, _ in ClauseSplitter()(text)]

    def stream(self, *, language: str | None = None) -> tokenize.SentenceStream:
        return token_stream.BufferedSentenceStream(tokenizer=ClauseSplitter(), min_token_len=SENTENCE_MIN, min_ctx_len=10)
