import numpy as np

from agent_worker.retranscribe import SR, assign, speech_pieces


def _tone(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (3000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def test_pieces_split_on_pauses_and_keep_order():
    silence = np.zeros(int(1.5 * SR), dtype=np.int16)
    x = np.concatenate([silence, _tone(2.0), silence, _tone(1.0), silence])
    pieces = speech_pieces(x)
    assert len(pieces) == 2
    (s1, e1, _), (s2, e2, _) = pieces
    assert 1.3 <= s1 <= 1.7 and 3.3 <= e1 <= 3.7 and s2 > e1


def test_long_speech_is_cut_under_the_request_limit():
    pieces = speech_pieces(_tone(60))
    assert len(pieces) >= 3 and all(e - s <= 25.1 for s, e, _ in pieces)


def test_pieces_go_to_the_turn_saved_after_them():
    turns = [{"seq": 1, "at_ms": 4000}, {"seq": 3, "at_ms": 9500}]
    pieces = [(1.0, 3.5, "mujhe jaanna tha"), (6.0, 7.0, "Schoollog ke baare mein"), (7.5, 9.2, "nahi pata"), (20.0, 21.0, "late")]
    assert assign(turns, pieces) == {1: "mujhe jaanna tha", 3: "Schoollog ke baare mein nahi pata"}


def test_single_words_keep_the_live_text():
    from agent_worker.retranscribe import worth_replacing
    assert not worth_replacing("No.", "हाँ 9.")            # seen on a real call: "no" heard as "nau" (nine)
    assert not worth_replacing("नहीं", "हाँ")
    assert worth_replacing("जान नहीं था हाँ हाँ बारे में", "मुझे जानना था school के बारे में")
    assert worth_replacing("Hello", "Hello Hello Hello हाँ Hello")
    assert not worth_replacing("same words here", "same words here")
