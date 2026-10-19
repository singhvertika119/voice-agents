from datetime import datetime, timedelta, timezone

from agent_worker.config import ensure_disclosure
from agent_worker.language import language_hint, style
from agent_worker.tools import CallState, describe_hours, normalize_phone, within_hours

IST = timezone(timedelta(hours=5, minutes=30))


def test_phone_numbers_are_normalised_and_validated():
    assert normalize_phone("98765 43210") == "+919876543210"
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("1234567890") is None      # Indian mobiles start with 6-9
    assert normalize_phone("98765") is None
    assert normalize_phone(None) is None


def test_business_hours_use_ist_and_listed_days():
    s = {"business_hours": {"days": [1, 2, 3, 4, 5, 6], "start": "09:00", "end": "19:00"}}
    assert within_hours(s, datetime(2026, 10, 19, 10, 30, tzinfo=IST))        # Monday 10:30
    assert not within_hours(s, datetime(2026, 10, 19, 19, 0, tzinfo=IST))      # closing time itself
    assert not within_hours(s, datetime(2026, 10, 18, 11, 0, tzinfo=IST))      # Sunday
    assert within_hours(s, datetime(2026, 10, 19, 4, 30, tzinfo=timezone.utc))  # 10:00 IST expressed in UTC


def test_hours_are_described_for_the_caller():
    assert describe_hours({"business_hours": {"days": [1, 2, 3, 4, 5, 6], "start": "09:00", "end": "19:00"}}) == "Monday to Saturday, 09:00 to 19:00 IST"


def test_call_outcome_comes_from_what_the_agent_did():
    s = CallState()
    assert s.outcome(False) == "dropped" and s.outcome(True) == "resolved"
    s.handoff_requested = True
    assert s.outcome(True) == "handed_off"
    s.callback_booked = True
    assert s.outcome(True) == "callback"


def test_disclosure_is_added_when_missing_and_not_duplicated():
    assert "AI assistant" in ensure_disclosure("Namaste, Sunrise Clinic mein swagat hai.")
    ok = "Namaste, main ek AI assistant hoon, yeh call record ho sakti hai."
    assert ensure_disclosure(ok) == ok


def test_language_style_detection():
    assert style("What are your timings?") == "english"
    assert style("consultation ki fees kitni hai") == "hinglish"
    assert style("क्लिनिक कब खुलता है") == "devanagari"
    assert language_hint("What are your timings?") and language_hint("fees kitni hai?") is None
