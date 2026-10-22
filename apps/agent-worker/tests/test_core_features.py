from datetime import datetime, timedelta, timezone

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


def test_international_numbers_from_phone_calls_are_kept():
    assert normalize_phone("+1 (415) 555-0100") == "+14155550100"
    assert normalize_phone("+14155550100") == "+14155550100"
    assert normalize_phone("0014155550100") == "+14155550100"
    assert normalize_phone("+44 20 7946 0958") == "+442079460958"
    assert normalize_phone("+919876543210") == "+919876543210"
    assert normalize_phone("+91 11 2345 6789") == "+911123456789"   # an Indian landline calling in
    assert normalize_phone("+91 98765") is None
    assert normalize_phone("+0123456789") is None
    assert normalize_phone("+123") is None
    assert normalize_phone("4155550100") is None                    # no + and not an Indian mobile


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


def test_voice_language_follows_the_text():
    from agent_worker.language import set_tts_language, tts_language
    assert tts_language("What are your timings on Sunday?", "hi-IN") == "en-IN"
    assert tts_language("consultation ki fees kitni hai", "en-IN") == "hi-IN"
    assert tts_language("क्लिनिक कब खुलता है", "en-IN") == "hi-IN"
    assert tts_language("yes", "hi-IN") == "hi-IN"            # one word is not enough to switch
    assert tts_language("yes", "en-IN") == "en-IN"

    class FakeSarvam:
        __module__ = "livekit.plugins.sarvam.tts"
        def update_options(self, **kw): self.kw = kw
    class FakeCartesia:
        __module__ = "livekit.plugins.cartesia.tts"
        def update_options(self, **kw): self.kw = kw
    class Chain:
        def __init__(self): self._tts_instances = [FakeSarvam(), FakeCartesia()]
    c = Chain()
    set_tts_language(c, "en-IN")
    assert c._tts_instances[0].kw == {"target_language_code": "en-IN"} and c._tts_instances[1].kw == {"language": "en"}


def test_language_style_detection():
    assert style("What are your timings?") == "english"
    assert style("consultation ki fees kitni hai") == "hinglish"
    assert style("क्लिनिक कब खुलता है") == "devanagari"
    assert language_hint("What are your timings?") and language_hint("fees kitni hai?") is None
