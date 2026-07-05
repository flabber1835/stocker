"""Selection-audit classification + structural-findings contract (no DB, no LLM).

classify_candidates is the pure heart of the selection audit: it must attribute
every non-pick to the right subsystem (vetter veto vs builder cap vs rank), because
the per-class forward-return spread built on it is what tells the evaluator whether
misses are FACTOR problems or CONSTRUCTION problems.
"""
from app.packet import classify_candidates, ARCHITECTURE_BRIEF
from app.report import REPORT_SCHEMA


def _c(t, rank):
    return {"ticker": t, "rank": rank, "score": 1.0, "sector": "Tech"}


def test_classification_attribution():
    candidates = [_c("AAA", 1), _c("BBB", 2), _c("CCC", 3), _c("DDD", 4), _c("EEE", 50)]
    selected = {"AAA", "DDD"}              # worst selected rank = 4
    excluded = {"BBB": "drawdown"}
    out = classify_candidates(candidates, selected, excluded, worst_selected_rank=4)
    by = {o["ticker"]: o for o in out}
    assert by["AAA"]["outcome"] == "selected"
    assert by["BBB"]["outcome"] == "vetter_excluded" and by["BBB"]["risk_type"] == "drawdown"
    # CCC ranked 3 < worst selected 4, not excluded, not picked → the BUILDER skipped it
    assert by["CCC"]["outcome"] == "cap_blocked"
    # EEE ranked 50 > 4 → never reached: a RANK decision, not a builder one
    assert by["EEE"]["outcome"] == "out_ranked"


def test_no_selection_means_no_cap_blocked():
    # cold start: nothing selected → worst rank None → nothing can be cap_blocked
    out = classify_candidates([_c("AAA", 1)], set(), {}, worst_selected_rank=None)
    assert out[0]["outcome"] == "out_ranked"


def test_structural_findings_in_contract():
    assert "structural_findings" in REPORT_SCHEMA["required"]
    props = REPORT_SCHEMA["properties"]["structural_findings"]["items"]["properties"]
    for k in ("finding", "category", "evidence", "suggested_approach", "confidence"):
        assert k in props
    cats = props["category"]["enum"]
    for c in ("missing_factor", "missing_data_source", "selection_logic", "exit_logic"):
        assert c in cats


def test_architecture_brief_covers_the_chain():
    # The brief is the LLM's mental model — it must at least name every stage and
    # the known non-features (the seed list for structural findings).
    for kw in ("INGEST", "FACTORS", "RANK", "VET", "BUILD", "DELTA", "RISK",
               "KNOWN NON-FEATURES", "greedy_select", "orphan"):
        assert kw in ARCHITECTURE_BRIEF, f"brief missing: {kw}"


def test_funnel_sections_wired_into_packet():
    """The full decision funnel must be evidenced: gates -> rank -> build -> risk.
    (The gate_audit is the 'what did the filters cost us' counterfactual — the
    recent-IPO blind spot is invisible without it.)"""
    import inspect
    from app import packet
    src = inspect.getsource(packet.build_packet)
    for section in ("gate_audit", "selection_audit", "factor_coverage",
                    "risk_gate_stats", "universe_snapshot", "system_architecture"):
        assert f'"{section}"' in src, f"packet missing section: {section}"


def test_prompt_teaches_the_new_sections():
    from app.report import SYSTEM_PROMPT
    for kw in ("GATE AUDIT", "FACTOR COVERAGE", "RISK-GATE STATS",
               "first-price", "filter mechanism"):
        assert kw in SYSTEM_PROMPT, f"prompt missing: {kw}"


def test_prior_reviews_feedback_loop_wired():
    """The evaluator must see its own prior output (iterate, don't restart)."""
    import inspect
    from app import packet
    src = inspect.getsource(packet.build_packet)
    assert '"prior_reviews"' in src
    assert '"hypotheses_ledger"' not in src  # dead placeholder replaced, not shipped as noise
    from app.report import SYSTEM_PROMPT
    for kw in ("prior_reviews", "ITERATE", "retract", "consecutive week"):
        assert kw in SYSTEM_PROMPT, f"prompt missing iteration rule: {kw}"
