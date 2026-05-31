"""Tests for the falling-knife drawdown signal in the vetter.

Three layers:
  - the pure helper app.drawdown.recent_drawdown
  - the prompt line emitted by _format_ticker_message(drawdown_21d=...)
  - the deterministic entry backstop logic (mirrors _do_vet's override rule)
"""
from app.drawdown import recent_drawdown
from app.vetter import _format_ticker_message, _detect_hallucination_flags, PER_TICKER_SCHEMA


# ── risk_type enum / drawdown category ───────────────────────────────────────

def test_drawdown_is_a_valid_risk_type():
    assert "drawdown" in PER_TICKER_SCHEMA["properties"]["risk_type"]["enum"]


def test_drawdown_exclude_not_flagged_as_dataless_contradiction():
    # A price-based drawdown exclusion legitimately has no news/search data and a
    # non-'none' risk_type — it must NOT trip the "exclude with no data" or
    # "exclude + risk_type=none" contradiction flags.
    parsed = {
        "exclude": True, "confidence": "high", "risk_type": "drawdown",
        "reason": "Severe recent drawdown of -31% vs 21-day peak; poor entry timing.",
        "positive_catalyst": False,
    }
    flags = _detect_hallucination_flags(
        "AMD", parsed, news=[], earnings_date=None, raw="{}", today="2026-05-30"
    )
    assert flags == []


# ── pure helper ──────────────────────────────────────────────────────────────

def test_at_peak_is_zero():
    assert recent_drawdown([100, 105, 110]) == 0.0


def test_below_peak():
    assert recent_drawdown([100, 120, 90]) == 90 / 120 - 1.0


def test_window_limits_lookback():
    # window=2 ignores the leading 100 → peak 120, last 90
    assert recent_drawdown([100, 120, 90], window=2) == 90 / 120 - 1.0


def test_empty_and_nonpositive_return_none():
    assert recent_drawdown([]) is None
    assert recent_drawdown([0, 0, 0]) is None
    assert recent_drawdown([None, None]) is None


def test_skips_nonpositive_but_uses_valid():
    # a corrupt 0.0 bar is ignored; peak/last computed from the valid ones
    assert recent_drawdown([100.0, 0.0, 80.0]) == 80.0 / 100.0 - 1.0


# ── prompt rendering ─────────────────────────────────────────────────────────

def _msg(**kw):
    return _format_ticker_message(
        "AMD", news=[], earnings_date=None, tavily_articles=[], today="2026-05-30", **kw
    )


def test_prompt_includes_drawdown_line():
    msg = _msg(drawdown_21d=-0.27)
    assert "Recent drawdown (21d" in msg
    assert "-27.0%" in msg
    assert "falling knife" in msg.lower()  # steep-drop warning fires at <= -20%


def test_prompt_mild_pullback_note():
    msg = _msg(drawdown_21d=-0.12)
    assert "-12.0%" in msg
    assert "pullback" in msg.lower()
    assert "falling knife" not in msg.lower()  # not steep enough for the strong warning


def test_prompt_no_drawdown_line_when_absent():
    assert "Recent drawdown" not in _msg(drawdown_21d=None)


def test_prompt_small_drawdown_has_no_warning_note():
    msg = _msg(drawdown_21d=-0.03)
    assert "-3.0%" in msg
    assert "pullback" not in msg.lower()
    assert "falling knife" not in msg.lower()


# ── deterministic backstop rule (mirrors _do_vet) ────────────────────────────
# The override condition in main._do_vet, isolated for unit testing.
# Source-of-truth / orphan-exit redesign: the backstop no longer exempts held
# names. A held falling-knife is force-excluded → dropped from the fresh target →
# the delta engine orphan-exits it. Data-gap names (dd is None) stay exempt.

def _backstop(result, dd, threshold=0.25):
    if threshold > 0 and dd is not None and dd <= -threshold and not result.get("exclude"):
        result = {**result, "exclude": True, "risk_type": "drawdown"}
    return result


def test_backstop_forces_exclude_on_severe_knife_entry():
    out = _backstop({"exclude": False}, dd=-0.30)
    assert out["exclude"] is True
    assert out["risk_type"] == "drawdown"  # surfaces as a DRAWDOWN badge, not NONE


def test_backstop_ignores_mild_drawdown():
    out = _backstop({"exclude": False}, dd=-0.18)
    assert out["exclude"] is False


def test_backstop_excludes_held_position_too():
    # Held name in a deep drawdown IS now force-excluded — it drops from the fresh
    # target and the delta engine orphan-exits it (the falling-knife-sells redesign).
    # The held-vs-not distinction only affects the audit wording, not the decision.
    out = _backstop({"exclude": False}, dd=-0.40)
    assert out["exclude"] is True
    assert out["risk_type"] == "drawdown"


def test_backstop_exempts_data_gap_names():
    # No recent price history → dd is None → never treated as a crash, never excluded.
    out = _backstop({"exclude": False}, dd=None)
    assert out["exclude"] is False


def test_backstop_threshold_is_inclusive():
    # the live rule is `dd <= -threshold`, so exactly at the limit DOES trigger
    out = _backstop({"exclude": False}, dd=-0.25, threshold=0.25)
    assert out["exclude"] is True
    # just inside the limit does not
    assert _backstop({"exclude": False}, dd=-0.249, threshold=0.25)["exclude"] is False


def test_backstop_disabled_when_threshold_zero():
    out = _backstop({"exclude": False}, dd=-0.90, threshold=0.0)
    assert out["exclude"] is False


def test_backstop_does_not_downgrade_an_llm_exclude():
    # already excluded by the LLM → untouched (stays excluded)
    out = _backstop({"exclude": True}, dd=-0.05)
    assert out["exclude"] is True
