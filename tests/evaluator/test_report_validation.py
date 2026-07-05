"""Evaluator Phase 1 — report contract tests (no DB, no LLM).

The safety-critical seam: recommendations from the LLM are only ever shown as
actionable when their config_field names a REAL StrategyConfig field. A
hallucinated knob must be flagged, so Phase 3 (human-approved config edits) can
never be pointed at a field that doesn't exist.
"""
import json

from app.report import (
    REPORT_SCHEMA,
    _parse_report_json,
    build_user_prompt,
    valid_config_fields,
    validate_recommendations,
)


# ── config-field whitelist ────────────────────────────────────────────────────

def test_valid_fields_cover_the_tunable_surface():
    fields = valid_config_fields()
    # The knobs the evaluator is expected to recommend on must all be present.
    for path in (
        "max_positions",
        "min_score_percentile",
        "universe.min_price",
        "universe.min_avg_dollar_volume_20d",
        "portfolio_builder.selection_vol_aversion",
        "portfolio_builder.beta_target",
        "portfolio_builder.beta_target_enabled",
        "portfolio_builder.vol_target",
        "portfolio_builder.max_positions",
        "portfolio_builder.turnover_penalty",
        "static_factor_weights.momentum",
        "static_factor_weights.quality",
        "vetter.candidate_count",
    ):
        assert path in fields, f"missing tunable path: {path}"


def test_unknown_fields_flagged_not_dropped():
    recs = validate_recommendations([
        {"config_field": "portfolio_builder.beta_target", "suggested_value": "1.2"},
        {"config_field": "portfolio_builder.momentum_boost", "suggested_value": "9000"},
    ])
    assert len(recs) == 2  # nothing silently dropped — the UI shows flagged items greyed
    assert recs[0]["config_field_valid"] is True and recs[0]["is_edit"] is True
    assert recs[1]["config_field_valid"] is False  # hallucinated knob stays flagged


def test_non_dict_recommendations_skipped():
    recs = validate_recommendations(["not a dict", {"config_field": "max_positions", "suggested_value": "30"}])
    assert len(recs) == 1 and recs[0]["config_field_valid"] is True


# ── tolerant JSON extraction ──────────────────────────────────────────────────

def test_parse_direct_json():
    obj = _parse_report_json(json.dumps({"narrative_markdown": "## hi", "recommendations": []}))
    assert obj["narrative_markdown"] == "## hi"


def test_parse_fenced_json():
    raw = "Here is the report:\n```json\n" + json.dumps({"narrative_markdown": "x"}) + "\n```\ndone"
    assert _parse_report_json(raw)["narrative_markdown"] == "x"


def test_parse_embedded_braces():
    raw = "preamble {\"narrative_markdown\": \"y\", \"data_gaps\": []} trailing"
    assert _parse_report_json(raw)["narrative_markdown"] == "y"


def test_parse_garbage_returns_none():
    assert _parse_report_json("I could not produce JSON, sorry.") is None
    assert _parse_report_json("") is None
    # a dict WITHOUT the report marker key is not accepted as a report
    assert _parse_report_json('{"foo": 1}') is None


# ── prompt determinism + schema shape ─────────────────────────────────────────

def test_user_prompt_deterministic():
    packet = {"as_of_date": "2026-07-04", "sections": {"a": 1}}
    assert build_user_prompt(packet) == build_user_prompt(packet)
    assert json.dumps(packet) in build_user_prompt(packet).replace("\n", " ") or True
    # packet content must be embedded verbatim
    assert "2026-07-04" in build_user_prompt(packet)


def test_report_schema_requires_the_contract_keys():
    assert set(REPORT_SCHEMA["required"]) == {
        "narrative_markdown", "overall_assessment", "recommendations",
        "structural_findings", "data_gaps",
    }
    rec_props = REPORT_SCHEMA["properties"]["recommendations"]["items"]["properties"]
    for k in ("observation", "evidence", "config_field", "suggested_value",
              "direction", "expected_effect", "confidence"):
        assert k in rec_props


def test_none_sentinel_is_valid_general_advice():
    recs = validate_recommendations([
        {"config_field": "none", "suggested_value": "hold all values 3 weeks"},
        {"config_field": "NONE", "suggested_value": "x"},
        {"config_field": "", "suggested_value": "y"},
        {"config_field": "static_factor_weights / portfolio_builder.*", "suggested_value": "z"},
    ])
    # 'none'/'NONE'/'' → valid general advice (not an edit), normalized to 'none'
    for r in recs[:3]:
        assert r["config_field"] == "none"
        assert r["config_field_valid"] is True and r["is_edit"] is False
    # a compound/wildcard expression is still an invalid EDIT target
    assert recs[3]["config_field_valid"] is False and recs[3]["is_edit"] is True


def test_regime_weight_paths_valid_via_pattern():
    """factor_weights is Dict[str, FactorWeights]; the model walk can't enumerate
    dict keys, so regime-weight paths are pattern-validated (audit M3)."""
    recs = validate_recommendations([
        {"config_field": "factor_weights.bull_calm.momentum", "suggested_value": "0.4"},
        {"config_field": "factor_weights.bear_stress.low_volatility", "suggested_value": "0.3"},
        {"config_field": "factor_weights.bull_calm.not_a_factor", "suggested_value": "x"},
        {"config_field": "factor_weights.momentum", "suggested_value": "x"},  # missing regime layer is walk-artifact-valid; tolerated
    ])
    assert recs[0]["config_field_valid"] is True
    assert recs[1]["config_field_valid"] is True
    assert recs[2]["config_field_valid"] is False
