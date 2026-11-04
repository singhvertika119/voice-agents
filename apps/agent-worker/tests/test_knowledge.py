from agent_worker.knowledge import KnowledgeBase, search_rows

TABLES = [{"name": "Prices", "columns": ["Service", "Price"],
           "rows": [{"Service": "ECG", "Price": "400"}, {"Service": "X-ray", "Price": "700"}, {"Service": "Consultation", "Price": "600"}]}]


def test_exact_row_found():
    assert search_rows(TABLES, "Prices", "ECG ka price")[0]["Price"] == "400"


def test_fuzzy_spelling_finds_row():
    assert search_rows(TABLES, "", "x ray")[0]["Price"] == "700"


def test_no_match_returns_empty():
    assert search_rows(TABLES, "", "dermatologist") == []


def test_prompt_addition_mentions_tables_and_documents():
    kb = KnowledgeBase(mode="prompt", prompt_text="Timings: 9 to 7.", tables=TABLES)
    out = kb.prompt_addition()
    assert "Timings: 9 to 7." in out and "Prices (columns: Service, Price)" in out and "Never guess" in out


def test_no_knowledge_adds_nothing():
    assert KnowledgeBase().prompt_addition() == ""


def test_keyword_terms_for_fallback_search():
    from agent_worker.knowledge import keyword_terms
    assert keyword_terms("What are the fees for ECG?") == ["what", "are", "the", "fees", "for", "ecg"]
    assert keyword_terms("ECG ki fees kitni hai, ECG?") == ["ecg", "fees", "kitni", "hai"]
    assert keyword_terms("a b") == []


# ---- D-111: no search for small talk; contact/about/location sections always in the prompt
from agent_worker.knowledge import CORE_SECTION, KnowledgeBase, is_small_talk  # noqa: E402


def test_small_talk_is_not_searched():
    for t in ["okay", "Haan ji", "thank you", "ठीक है।", "Hello?", "bye"]:
        assert is_small_talk(t), t
    for t in ["Nialabs ka office kahan hai?", "haan mujhe price batao", "NiaFace A100", ""]:
        assert not is_small_talk(t), t


def test_key_fact_sections():
    assert CORE_SECTION.search("Contact Nialabs (/contact-us) > Let's Talk")
    assert CORE_SECTION.search("About Us (/about-us)")
    assert CORE_SECTION.search("Jaipur (/locations/jaipur)")
    assert CORE_SECTION.search("On every page of the website")
    assert not CORE_SECTION.search("Glossary (/glossary/contactless-biometrics)")
    assert not CORE_SECTION.search("NiaFace A100 (/products/niaface-a100) > Specs")


def test_key_facts_only_in_search_mode():
    kb = KnowledgeBase(mode="search", core_text="Our Location: B-515, Jaipur")
    assert "B-515" in kb.prompt_addition()
    assert "B-515" not in KnowledgeBase(mode="prompt", prompt_text="x", core_text="Our Location: B-515").prompt_addition()


def test_retrieve_skips_small_talk():
    import asyncio
    kb = KnowledgeBase(mode="search")
    assert asyncio.run(kb.retrieve("okay")) is None


def test_acknowledgements_are_not_greetings():
    from agent_worker.knowledge import is_acknowledgement
    for t in ["OK", "Okay", "हम्म Nice", "ठीक है।", "haan ji"]:
        assert is_acknowledgement(t), t
    for t in ["Hello", "bye", "Is integrations available", "namaste"]:
        assert not is_acknowledgement(t), t
