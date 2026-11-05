"""The voice may start at the first comma of a reply, then speaks whole sentences (D-115)."""
import os

from agent_worker.speech_chunks import ClauseSplitter, ClauseTokenizer


def pieces(text: str) -> list[str]:
    return [p for p, _, _ in ClauseSplitter()(text)]


def test_first_piece_can_end_at_a_comma():
    assert pieces("Ji, hamara head office Jaipur mein hai, E-42 Reyansh Tower") == [
        "Ji, hamara head office Jaipur mein hai,", "E-42 Reyansh Tower"]


def test_short_opening_is_not_cut():
    # "Ji," alone is too short to sound right
    assert pieces("Ji, bilkul") == ["Ji, bilkul"]


def test_later_commas_are_not_cut():
    out = pieces("Our office is open from nine to six. We are closed on Sunday, Monday is a holiday too, sorry.")
    assert out == ["Our office is open from nine to six.", "We are closed on Sunday, Monday is a holiday too, sorry."]


def test_numbers_with_commas_stay_whole():
    out = pieces("The yearly fee for grade eight is Rs 1,20,000 in total for the year.")
    assert out == ["The yearly fee for grade eight is Rs 1,20,000 in total for the year."]


def test_hindi_sentence_end():
    assert pieces("हमारा ऑफिस जयपुर में है और सुबह नौ बजे खुलता है। रविवार को बंद रहता है।") == [
        "हमारा ऑफिस जयपुर में है और सुबह नौ बजे खुलता है।", "रविवार को बंद रहता है।"]


def test_one_early_cut_per_reply_across_calls():
    split = ClauseSplitter()
    first = split("Sure, our phone number for sales and support is, plus")
    assert [p for p, _, _ in first] == ["Sure, our phone number for sales and support is,", "plus"]
    later = split("plus nine one eight, four four eight, and so on until the end. Thank you.")
    assert [p for p, _, _ in later] == ["plus nine one eight, four four eight, and so on until the end.", "Thank you."]


def test_stream_emits_first_clause_before_sentence_ends():
    async def run():
        s = ClauseTokenizer().stream()
        s.push_text("Ji, hamara head office Jaipur mein hai, E-42 Reyansh")
        s.end_input()
        return [t.token async for t in s]

    import asyncio
    assert asyncio.run(run())[0] == "Ji, hamara head office Jaipur mein hai,"


def test_sarvam_voice_uses_the_clause_splitter(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", os.getenv("SARVAM_API_KEY") or "test-key")
    from agent_worker import providers
    voice = providers._tts({"provider": "sarvam", "model": "bulbul:v3", "speaker": "ritu"}, "hi-IN")
    assert isinstance(voice._opts.word_tokenizer, ClauseTokenizer)
    assert voice._opts.min_buffer_size == 30
    stt = providers._stt({"provider": "sarvam", "model": "saaras:v3", "mode": "codemix"}, "hi-IN")
    assert stt._opts.flush_signal is True
