"""
Tests for the vetter join logic in /delta/latest.

The API joins vetter_decisions from the most recent successful vetter run onto
each delta intent. We simulate the join in Python to verify the selection logic,
the merge behavior, and the fallback when no vetter run exists.
"""
from __future__ import annotations


# ── Simulated join helpers (mirror services/api/app/main.py logic) ───────────

def _select_vetter_run(vetter_runs: list[dict]) -> dict | None:
    """Simulate: SELECT run_id FROM vetter_runs WHERE status='success' ORDER BY started_at DESC LIMIT 1"""
    successful = [r for r in vetter_runs if r["status"] == "success"]
    if not successful:
        return None
    return max(successful, key=lambda r: r["started_at"])


def _build_vetter_by_ticker(
    vetter_run: dict | None,
    vetter_decisions: list[dict],
    tickers: list[str],
) -> dict[str, dict]:
    """Simulate: SELECT ... FROM vetter_decisions WHERE run_id=? AND ticker=ANY(?)"""
    if vetter_run is None:
        return {}
    rid = vetter_run["run_id"]
    result: dict[str, dict] = {}
    for d in vetter_decisions:
        if d["run_id"] == rid and d["ticker"] in tickers:
            result[d["ticker"]] = d
    return result


def _merge_intents(
    intents: list[dict],
    vetter_by_ticker: dict[str, dict],
) -> list[dict]:
    """Mirror the intent dict construction in /delta/latest response."""
    merged = []
    for r in intents:
        v = vetter_by_ticker.get(r["ticker"], {})
        merged.append({
            **r,
            "vetter_excluded":          v.get("exclude"),
            "vetter_confidence":        v.get("confidence"),
            "vetter_risk_type":         v.get("risk_type"),
            "vetter_reason":            v.get("reason"),
            "vetter_crashed":           bool(v.get("crashed", False)),
            "vetter_positive_catalyst": v.get("positive_catalyst"),
            "vetter_positive_reason":   v.get("positive_reason"),
        })
    return merged


# ── Fixtures ──────────────────────────────────────────────────────────────────

INTENTS = [
    {"ticker": "AAPL", "action": "entry", "rank": 1},
    {"ticker": "MSFT", "action": "entry", "rank": 2},
    {"ticker": "NVDA", "action": "hold",  "rank": 3},
    {"ticker": "GOOGL", "action": "exit", "rank": 50},
]

VETTER_RUNS = [
    {"run_id": "run-a", "status": "success",  "started_at": 100},
    {"run_id": "run-b", "status": "failed",   "started_at": 200},
    {"run_id": "run-c", "status": "success",  "started_at": 150},
]

VETTER_DECISIONS = [
    # run-a decisions
    {"run_id": "run-a", "ticker": "AAPL",  "exclude": False, "confidence": "high",   "risk_type": "none",  "reason": "Strong earnings", "positive_catalyst": True,  "positive_reason": "AI demand",    "crashed": False},
    {"run_id": "run-a", "ticker": "MSFT",  "exclude": True,  "confidence": "medium", "risk_type": "legal", "reason": "Antitrust risk",  "positive_catalyst": None,  "positive_reason": None,           "crashed": False},
    # run-c decisions (this is actually the most recent successful run)
    {"run_id": "run-c", "ticker": "AAPL",  "exclude": False, "confidence": "high",   "risk_type": "none",  "reason": "Upgraded",        "positive_catalyst": True,  "positive_reason": "Cloud growth", "crashed": False},
    {"run_id": "run-c", "ticker": "NVDA",  "exclude": False, "confidence": "high",   "risk_type": "none",  "reason": "GPU demand",      "positive_catalyst": True,  "positive_reason": "AI chips",     "crashed": False},
    # crashed decision — LLM call failed for GOOGL
    {"run_id": "run-c", "ticker": "GOOGL", "exclude": False, "confidence": "low",    "risk_type": "none",  "reason": "Ticker vetting crashed: timeout", "positive_catalyst": False, "positive_reason": None, "crashed": True},
]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestVetterRunSelection:
    def test_most_recent_successful_run_is_selected(self):
        """run-c (started_at=150) should win over run-a (started_at=100); run-b is failed."""
        vr = _select_vetter_run(VETTER_RUNS)
        assert vr is not None
        assert vr["run_id"] == "run-c"

    def test_failed_runs_are_excluded(self):
        runs = [
            {"run_id": "x", "status": "failed",  "started_at": 999},
            {"run_id": "y", "status": "success", "started_at": 1},
        ]
        vr = _select_vetter_run(runs)
        assert vr["run_id"] == "y"

    def test_no_successful_run_returns_none(self):
        runs = [{"run_id": "x", "status": "failed", "started_at": 100}]
        assert _select_vetter_run(runs) is None

    def test_empty_runs_returns_none(self):
        assert _select_vetter_run([]) is None


class TestVetterByTickerBuild:
    def test_only_selected_run_decisions_used(self):
        """run-a decisions must not appear when run-c is selected."""
        vr = _select_vetter_run(VETTER_RUNS)
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL"]
        vbt = _build_vetter_by_ticker(vr, VETTER_DECISIONS, tickers)
        # AAPL appears in both run-a and run-c; only run-c's reason should be present
        assert vbt["AAPL"]["reason"] == "Upgraded"

    def test_tickers_not_in_decisions_are_absent(self):
        """MSFT is only in run-a, not run-c → absent from vbt. GOOGL is in run-c as a crash."""
        vr = _select_vetter_run(VETTER_RUNS)
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL"]
        vbt = _build_vetter_by_ticker(vr, VETTER_DECISIONS, tickers)
        assert "MSFT" not in vbt   # MSFT only in run-a, not in run-c
        assert "GOOGL" in vbt      # GOOGL is in run-c as a crashed decision
        assert vbt["GOOGL"]["crashed"] is True

    def test_tickers_filter_restricts_to_requested(self):
        """Only tickers in the requested list are returned even if more exist in decisions."""
        vr = _select_vetter_run(VETTER_RUNS)
        vbt = _build_vetter_by_ticker(vr, VETTER_DECISIONS, ["AAPL"])  # only ask for AAPL
        assert "AAPL" in vbt
        assert "NVDA" not in vbt

    def test_none_vetter_run_gives_empty_dict(self):
        vbt = _build_vetter_by_ticker(None, VETTER_DECISIONS, ["AAPL"])
        assert vbt == {}


class TestIntentMerge:
    def _merged(self) -> list[dict]:
        vr = _select_vetter_run(VETTER_RUNS)
        tickers = [r["ticker"] for r in INTENTS]
        vbt = _build_vetter_by_ticker(vr, VETTER_DECISIONS, tickers)
        return _merge_intents(INTENTS, vbt)

    def test_vetter_fields_present_on_all_intents(self):
        merged = self._merged()
        for r in merged:
            assert "vetter_excluded" in r
            assert "vetter_confidence" in r
            assert "vetter_risk_type" in r
            assert "vetter_reason" in r
            assert "vetter_positive_catalyst" in r
            assert "vetter_positive_reason" in r

    def test_aapl_gets_vetter_data(self):
        merged = self._merged()
        aapl = next(r for r in merged if r["ticker"] == "AAPL")
        assert aapl["vetter_excluded"] is False
        assert aapl["vetter_confidence"] == "high"
        assert aapl["vetter_reason"] == "Upgraded"
        assert aapl["vetter_positive_catalyst"] is True

    def test_googl_gets_crashed_vetter_data(self):
        """GOOGL has a crashed decision in run-c — vetter_crashed=True, exclude=False (KEEP)."""
        merged = self._merged()
        googl = next(r for r in merged if r["ticker"] == "GOOGL")
        assert googl["vetter_crashed"] is True
        assert googl["vetter_excluded"] is False   # crash → KEEP

    def test_nvda_hold_still_gets_vetter_data(self):
        """Even hold intents get vetter overlay — vetting is per-ticker, not per-action."""
        merged = self._merged()
        nvda = next(r for r in merged if r["ticker"] == "NVDA")
        assert nvda["vetter_confidence"] == "high"
        assert nvda["vetter_reason"] == "GPU demand"

    def test_no_vetter_run_gives_null_fields(self):
        """When no successful vetter run exists, all vetter fields are null."""
        merged = _merge_intents(INTENTS, {})
        for r in merged:
            assert r["vetter_excluded"] is None
            assert r["vetter_confidence"] is None

    def test_original_intent_fields_preserved(self):
        """Merge must not drop or modify the core intent fields."""
        merged = self._merged()
        aapl = next(r for r in merged if r["ticker"] == "AAPL")
        assert aapl["action"] == "entry"
        assert aapl["rank"] == 1


class TestVetterExclusionInDeltaContext:
    """
    Higher-level scenario: portfolio-builder already excluded MSFT via vetter_exclusions.
    The delta shows MSFT as a non-entry (e.g. watch/hold). The API should still surface
    the vetter verdict so the dashboard can explain why MSFT was skipped.
    """

    def test_excluded_ticker_not_in_entry_still_shows_vetter_verdict(self):
        # Simulate: MSFT excluded by vetter → portfolio-builder dropped it → it's a 'watch' in delta
        intents = [{"ticker": "MSFT", "action": "watch", "rank": 5}]
        vetter_runs = [{"run_id": "r1", "status": "success", "started_at": 1}]
        decisions = [
            {"run_id": "r1", "ticker": "MSFT", "exclude": True, "confidence": "high",
             "risk_type": "legal", "reason": "Antitrust probe", "positive_catalyst": None,
             "positive_reason": None}
        ]
        vr = _select_vetter_run(vetter_runs)
        vbt = _build_vetter_by_ticker(vr, decisions, ["MSFT"])
        merged = _merge_intents(intents, vbt)
        msft = merged[0]
        assert msft["action"] == "watch"
        assert msft["vetter_excluded"] is True
        assert msft["vetter_reason"] == "Antitrust probe"


class TestVetterCrashedField:
    """
    vetter_crashed must be a boolean sourced from the DB crashed column,
    not inferred by scanning vetter_reason for the word 'CRASHED'.

    The dashboard previously did:
        const crashed = vetter_reason.toUpperCase().indexOf('CRASHED') !== -1
    which fires falsely when the LLM writes 'the stock has crashed' in a
    legitimate EXCLUDE reason. The fix: API exposes crashed as vetter_crashed;
    dashboard reads r.vetter_crashed directly.
    """

    def _merged(self) -> list[dict]:
        vr = _select_vetter_run(VETTER_RUNS)
        tickers = [r["ticker"] for r in INTENTS]
        vbt = _build_vetter_by_ticker(vr, VETTER_DECISIONS, tickers)
        return _merge_intents(INTENTS, vbt)

    def test_vetter_crashed_field_present_on_all_intents(self):
        merged = self._merged()
        for r in merged:
            assert "vetter_crashed" in r

    def test_non_crashed_decision_gives_false(self):
        merged = self._merged()
        aapl = next(r for r in merged if r["ticker"] == "AAPL")
        assert aapl["vetter_crashed"] is False

    def test_crashed_decision_gives_true(self):
        merged = self._merged()
        googl = next(r for r in merged if r["ticker"] == "GOOGL")
        assert googl["vetter_crashed"] is True

    def test_no_vetter_data_gives_false(self):
        """Ticker with no vetter decision → vetter_crashed defaults to False."""
        intents = [{"ticker": "ZZZ", "action": "entry", "rank": 99}]
        merged = _merge_intents(intents, {})
        assert merged[0]["vetter_crashed"] is False

    def test_exclude_with_crashed_word_in_reason_not_misclassified(self):
        """
        A legitimate EXCLUDE whose reason text contains 'crashed' must not
        be misidentified as a technical crash. vetter_crashed=False means
        the LLM ran successfully and returned a real verdict.
        """
        decisions = [{
            "run_id": "r1", "ticker": "FUTU",
            "exclude": True, "confidence": "high",
            "risk_type": "regulatory",
            "reason": "Regulatory crackdown has crashed mainland China revenue; high litigation risk.",
            "positive_catalyst": False, "positive_reason": None,
            "crashed": False,  # LLM ran fine — this is a real EXCLUDE verdict
        }]
        vr = {"run_id": "r1", "status": "success", "started_at": 1}
        vbt = _build_vetter_by_ticker(vr, decisions, ["FUTU"])
        merged = _merge_intents([{"ticker": "FUTU", "action": "entry", "rank": 35}], vbt)
        futu = merged[0]
        assert futu["vetter_excluded"] is True
        assert futu["vetter_crashed"] is False  # NOT a crash — real EXCLUDE

    def test_actual_crash_does_not_exclude(self):
        """Technical crash → exclude=False (default KEEP), crashed=True."""
        decisions = [{
            "run_id": "r1", "ticker": "FUTU",
            "exclude": False, "confidence": "low",
            "risk_type": "none",
            "reason": "Ticker vetting crashed: ReadTimeout",
            "positive_catalyst": False, "positive_reason": None,
            "crashed": True,
        }]
        vr = {"run_id": "r1", "status": "success", "started_at": 1}
        vbt = _build_vetter_by_ticker(vr, decisions, ["FUTU"])
        merged = _merge_intents([{"ticker": "FUTU", "action": "entry", "rank": 35}], vbt)
        futu = merged[0]
        assert futu["vetter_excluded"] is False   # crash → KEEP
        assert futu["vetter_crashed"] is True     # but flagged for the user
