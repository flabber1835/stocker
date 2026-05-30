"""Tests for the falling-knife drawdown signal in the vetter.

Three layers:
  - the pure helper app.drawdown.recent_drawdown
  - the prompt line emitted by _format_ticker_message(drawdown_21d=...)
  - the deterministic entry backstop logic (mirrors _do_vet's override rule)
"""
from app.drawdown import recent_drawdown
from app.vetter import _format_ticker_message


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

def _backstop(result, dd, held, threshold=0.25):
    if threshold > 0 and dd is not None and dd <= -threshold and not held and not result.get("exclude"):
        result = {**result, "exclude": True}
    return result


def test_backstop_forces_exclude_on_severe_knife_entry():
    out = _backstop({"exclude": False}, dd=-0.30, held=False)
    assert out["exclude"] is True


def test_backstop_ignores_mild_drawdown():
    out = _backstop({"exclude": False}, dd=-0.18, held=False)
    assert out["exclude"] is False


def test_backstop_never_excludes_held_position():
    # held name in a deep drawdown must NOT be force-excluded (exclusion only
    # blocks buying; held positions are exited via rank, never by the vetter)
    out = _backstop({"exclude": False}, dd=-0.40, held=True)
    assert out["exclude"] is False


def test_backstop_threshold_is_inclusive():
    # the live rule is `dd <= -threshold`, so exactly at the limit DOES trigger
    out = _backstop({"exclude": False}, dd=-0.25, threshold=0.25, held=False)
    assert out["exclude"] is True
    # just inside the limit does not
    assert _backstop({"exclude": False}, dd=-0.249, threshold=0.25, held=False)["exclude"] is False


def test_backstop_disabled_when_threshold_zero():
    out = _backstop({"exclude": False}, dd=-0.90, held=False, threshold=0.0)
    assert out["exclude"] is False


def test_backstop_does_not_downgrade_an_llm_exclude():
    # already excluded by the LLM → untouched (stays excluded)
    out = _backstop({"exclude": True}, dd=-0.05, held=False)
    assert out["exclude"] is True
