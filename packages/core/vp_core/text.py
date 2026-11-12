"""Small text rules shared by the voice agent (speaking model replies) and the ingestion worker (storing knowledge)."""
import re

_RUPEES = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+)")


def spoken_rupees(text: str) -> str:
    """"₹1,500" / "Rs. 1500" / "INR 1500" -> "1500 rupees", which every voice reads correctly."""
    return _RUPEES.sub(lambda m: f"{m.group(1).replace(',', '')} rupees", text)
