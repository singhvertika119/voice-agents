"""Tests for Phase 4 Tools resilience (Bugs 2.15, 2.18)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from agent_worker.tools import IST, describe_hours, normalize_phone, within_hours


def test_normalize_phone_accepts_landlines():
    # 0 + STD + 7 digits (Jaipur)
    assert normalize_phone("0141 2345678") == "+911412345678"
    # 0 + STD (2 digits) + 8 digits (Delhi/Mumbai)
    assert normalize_phone("011 23456789") == "+911123456789"
    # Mobile without prefix
    assert normalize_phone("9876543210") == "+919876543210"
    # International format with +91
    assert normalize_phone("+91 141 2345678") == "+911412345678"


def test_within_hours_handles_overnight_and_normalizes_times():
    # Overnight hours: 20:00 to 02:00
    settings = {"business_hours": {"days": [1, 2, 3, 4, 5, 6, 7], "start": "20:00", "end": "02:00"}}

    # Monday 22:00 -> open
    t_open_night = datetime(2026, 11, 16, 22, 0, tzinfo=IST)
    assert within_hours(settings, t_open_night) is True

    # Tuesday 01:30 -> open
    t_open_early = datetime(2026, 11, 17, 1, 30, tzinfo=IST)
    assert within_hours(settings, t_open_early) is True

    # Tuesday 05:00 -> closed
    t_closed = datetime(2026, 11, 17, 5, 0, tzinfo=IST)
    assert within_hours(settings, t_closed) is False

    # Single-digit hour without leading zero: "9:00" -> "09:00"
    settings_no_pad = {"business_hours": {"days": [1, 2, 3, 4, 5], "start": "9:00", "end": "19:00"}}
    t_midday = datetime(2026, 11, 16, 12, 0, tzinfo=IST)
    assert within_hours(settings_no_pad, t_midday) is True


def test_describe_hours_contiguous_vs_non_contiguous():
    # Non-contiguous days
    settings_odd = {"business_hours": {"days": [1, 3, 5], "start": "09:00", "end": "18:00"}}
    desc = describe_hours(settings_odd)
    assert "Monday, Wednesday, Friday" in desc
    assert "Monday to Friday" not in desc

    # Contiguous days
    settings_cont = {"business_hours": {"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"}}
    desc_cont = describe_hours(settings_cont)
    assert "Monday to Friday" in desc_cont

    # Day 0 or 8 does not cause IndexError
    settings_invalid_days = {"business_hours": {"days": [0, 1, 8], "start": "09:00", "end": "18:00"}}
    desc_safe = describe_hours(settings_invalid_days)
    assert "Monday" in desc_safe
