from agent_worker.pii import redact, verhoeff_ok


def make_aadhaar(first11: str) -> str:
    for c in "0123456789":
        if verhoeff_ok(first11 + c):
            return first11 + c
    raise AssertionError


def test_valid_aadhaar_is_removed_in_spoken_forms():
    a = make_aadhaar("23456789012")
    assert "[AADHAAR]" in redact(f"mera aadhaar {a} hai")
    spaced = f"{a[:4]} {a[4:8]} {a[8:]}"
    assert "[AADHAAR]" in redact(f"aadhaar {spaced}")
    assert "[AADHAAR]" in redact("aadhaar " + " ".join(a))


def test_random_twelve_digits_that_fail_the_checksum_are_not_aadhaar():
    assert "[AADHAAR]" not in redact("order number 234567890123")


def test_card_number_removed_by_luhn():
    assert "[CARD]" in redact("card 4111 1111 1111 1111 expiry 12/28")


def test_pan_removed():
    assert redact("PAN ABCDE1234F hai") == "PAN [PAN] hai"


def test_phone_number_is_kept_for_callbacks():
    assert "9876543210" in redact("number 9876543210 par call karna")
    assert "9 8 7 6 5 4 3 2 1 0" in redact("number 9 8 7 6 5 4 3 2 1 0")


def test_long_account_like_numbers_removed():
    assert "[NUMBER]" in redact("account 123456789012345")


def test_plain_text_untouched():
    assert redact("Consultation fee is 600 rupees at 9 am.") == "Consultation fee is 600 rupees at 9 am."
