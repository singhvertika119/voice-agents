"""The callback tool checks that the agent really read the number back before booking (D-106)."""
from types import SimpleNamespace as NS

from agent_worker.tools import read_back

NUM = "+919876543210"


def ctx(*messages):
    items = [NS(role=r, text_content=t) for r, t in messages]
    return NS(session=NS(history=NS(items=items)))


def test_number_read_back_in_last_reply():
    c = ctx(("user", "mera number 9876543210"), ("assistant", "Aapka number 9, 8, 7, 6, 5, 4, 3, 2, 1, 0 hai, sahi hai?"), ("user", "haan"))
    assert read_back(c, NUM) is True


def test_number_read_back_in_devanagari_digits():
    assert read_back(ctx(("assistant", "आपका नंबर ९८७६५४३२१० है, सही है?")), NUM) is True


def test_number_never_read_back():
    c = ctx(("assistant", "Kya aap mujhe apna phone number de sakte hain?"), ("user", "Sure, 9 8 7 6 5 4 3 2 1 0"))
    assert read_back(c, NUM) is False


def test_old_read_back_does_not_count():
    c = ctx(("assistant", "9876543210, sahi hai?"), ("assistant", "Theek hai."), ("assistant", "Aur kuch?"))
    assert read_back(c, NUM) is False


def test_unreadable_history_leaves_decision_to_the_flag():
    assert read_back(NS(), NUM) is None
