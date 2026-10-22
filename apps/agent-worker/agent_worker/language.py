"""Which language is the caller using right now? Cheap script and word checks, no model call."""
from __future__ import annotations

# Only words that are not also English ("me", "so", "ho", "main" are left out on purpose).
HINDI_WORDS = set("hai hain hoon kya aap aapka aapki aapko mujhe mera meri mein nahi nahin haan karna karein kijiye chahiye "
                  "chahte milta milti milega kitna kitni kab kahan kaise jankari batayein bataiye abhi jald lekin toh".split())


def style(text: str) -> str:
    """devanagari | hinglish | english, by script and common romanised Hindi words."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum("\u0900" <= c <= "\u097f" for c in letters) / len(letters) > 0.3:
        return "devanagari"
    words = [x.strip(".,?!\"'").lower() for x in text.split()]
    return "hinglish" if sum(x in HINDI_WORDS for x in words) >= 2 else "english"


def tts_language(text: str, current: str) -> str:
    """The voice language for a reply to `text`. The voice reads digits and numbers in the language it is set to, so an
    English conversation on a Hindi-set voice says "600" in Hindi and the rest in English. English text gets en-IN,
    romanised or Devanagari Hindi gets hi-IN; too little text to tell keeps the current setting."""
    s = style(text)
    if s == "english":
        return "en-IN" if len(text.split()) >= 2 else current
    return "hi-IN"


def set_tts_language(tts_obj, code: str) -> None:
    """Point every speech provider in the chain (primary and backup) at `code`. Never raises: a provider that cannot
    switch keeps speaking in its current language, which is the old behaviour."""
    for inst in getattr(tts_obj, "_tts_instances", None) or [tts_obj]:
        try:
            module = type(inst).__module__
            if "sarvam" in module:
                inst.update_options(target_language_code=code)
            elif "cartesia" in module:
                inst.update_options(language=code.split("-")[0])
        except Exception:
            pass


def language_hint(caller_text: str) -> str | None:
    """A one-line reminder for the model. Only English needs it: models drift into Hindi after a Hindi greeting."""
    if style(caller_text) == "english" and len(caller_text.split()) >= 2:
        return "The caller is speaking English. Reply in English only, in this and later replies, until they use Hindi."
    return None
