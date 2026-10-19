from agent_worker.normalize import normalize_for_speech as n


def test_money():
    assert n("Fees Rs 600 only") == "Fees 600 rupees only"
    assert n("₹1,250") == "1250 rupees"


def test_markup_and_urls_removed():
    assert n("**Hello** see https://x.com now") == "Hello see now"


def test_phone_digits_spaced():
    assert n("Call 9876543210") == "Call 9 8 7 6 5 4 3 2 1 0"


def test_doctor_and_days():
    assert n("Dr. Sharma on Mon") == "Doctor Sharma on Monday"
