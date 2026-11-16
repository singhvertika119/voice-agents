"""Tests for Phase 4 Chunking & Voice Normalization resilience (Bug 2.17)."""
from __future__ import annotations

import pytest
from ingestion.chunking import TARGET_CHARS, chunk_markdown, normalize_for_voice


def test_normalize_preserves_std_codes_and_emails():
    text = "Call us at (022) 2345 6789 or email first_last@example.com for help."
    out = normalize_for_voice(text)
    assert "(022) 2345 6789" in out
    assert "first_last@example.com" in out


def test_normalize_rewrites_markdown_links_before_stripping_urls():
    text = "Please [Book online](https://clinic.example.com/book) for appointments."
    out = normalize_for_voice(text)
    assert "Book online" in out
    assert "http" not in out
    assert "[Book online](" not in out


def test_normalize_handles_rupees_with_paise():
    text = "Total amount due is Rs. 1,500.50 including taxes."
    out = normalize_for_voice(text)
    assert "1500.50 rupees" in out
    assert "1500 rupees.50" not in out


def test_chunking_splits_long_menu_without_periods():
    # Long list of menu items separated only by newlines
    lines = [f"Item number {i}: Veg special dish with paneer and spices" for i in range(100)]
    md = "# Menu\n\n" + "\n".join(lines)
    chunks = chunk_markdown(md)
    assert len(chunks) > 1
    # Chunks should be within comfortable bounds
    for c in chunks:
        assert len(c.content) <= TARGET_CHARS + 200


def test_heading_only_document_produces_chunks():
    md = "# Dr. Sharma Clinic\n\n## Cardiology\n\n## Neurology\n\n## Pediatrics"
    chunks = chunk_markdown(md)
    assert len(chunks) >= 3
    sections = [c.section for c in chunks]
    assert any("Cardiology" in s for s in sections)
