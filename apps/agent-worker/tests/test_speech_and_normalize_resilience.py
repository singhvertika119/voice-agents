"""Tests for Phase 4 Speech & Normalization resilience (Bug 2.16)."""
from __future__ import annotations

import pytest
from agent_worker.normalize import normalize_for_speech
from agent_worker.speech_chunks import ClauseSplitter


def test_clause_splitter_does_not_cut_after_abbreviations():
    splitter = ClauseSplitter()
    text = "The doctor on duty is Dr. Sharma and the consultation fee is Rs. 1500 per visit."
    pieces = splitter(text)
    texts = [p[0] for p in pieces]
    # "Dr." or "Rs." should not be cut as separate piece
    assert not any(t == "Dr." or t.endswith("Rs.") for t in texts)


def test_normalize_large_rupee_amount_not_split_digit_by_digit():
    # Large rupee amounts should not have their digits spaced out like phone numbers
    out = normalize_for_speech("The property price is Rs 1500000.")
    assert "1500000 rupees" in out
    assert "1 5 0 0 0 0 0" not in out


def test_normalize_does_not_convert_sun_pharma():
    out = normalize_for_speech("He works at Sun Pharma in Mumbai.")
    assert "Sun Pharma" in out
    assert "Sunday Pharma" not in out
