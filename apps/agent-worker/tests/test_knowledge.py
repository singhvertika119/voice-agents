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
