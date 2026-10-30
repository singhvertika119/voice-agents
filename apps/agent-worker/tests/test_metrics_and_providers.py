from agent_worker.call_metrics import RATES, CallMetricsLog


def test_cached_input_is_billed_at_half(tmp_path):
    m = CallMetricsLog(tmp_path, "c1", "a1")
    m.totals.update({"llm_in": 10_000, "llm_cached": 8_000})
    expected = 2_000 * RATES["llm_in_per_tok"] + 8_000 * RATES["llm_in_per_tok"] * 0.5
    assert abs(m.cost_usd() - expected) < 1e-12


def test_gemini_gets_its_own_timeout_over_googles_minimum(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    from agent_worker import providers
    g = providers._llm({"provider": "gemini", "model": "gemini-2.5-flash"}, 200)
    assert g._opts.http_options.timeout >= 10_000
