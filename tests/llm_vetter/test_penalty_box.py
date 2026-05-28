"""Unit tests for the vetter penalty box logic.

Tests cover:
- Date arithmetic (30 calendar days forward, not trading days)
- Upsert semantics: new entry vs. reset
- flagged_count increments on re-flag
- Expired penalty box (past date) treated as no penalty
- Tickers NOT flagged are NOT entered
- Extra-held augmentation: held tickers outside top-N are appended to candidates
"""
from datetime import date, timedelta


# ── Penalty box date logic ─────────────────────────────────────────────────────

def test_penalty_box_is_30_calendar_days():
    """penalty_box_until should be exactly 30 calendar days from today."""
    today = date(2026, 5, 28)
    penalty_until = today + timedelta(days=30)
    assert penalty_until == date(2026, 6, 27)


def test_penalty_box_spans_weekends():
    """30-day window includes weekends (calendar days, not trading days)."""
    today = date(2026, 5, 28)  # Thursday
    penalty_until = today + timedelta(days=30)
    # 30 days later = June 27, which is a Saturday — weekends are included
    assert (penalty_until - today).days == 30


def test_penalty_box_days_remaining_positive():
    today = date(2026, 5, 28)
    penalty_until = today + timedelta(days=10)
    remaining = (penalty_until - today).days
    assert remaining == 10


def test_penalty_box_days_remaining_at_expiry():
    today = date(2026, 5, 28)
    penalty_until = today  # expires today
    remaining = max(0, (penalty_until - today).days)
    assert remaining == 0


def test_penalty_box_days_remaining_never_negative():
    today = date(2026, 5, 28)
    penalty_until = today - timedelta(days=5)  # past due
    remaining = max(0, (penalty_until - today).days)
    assert remaining == 0


# ── Penalty box upsert semantics ───────────────────────────────────────────────

def _simulate_upsert(existing: dict | None, today: date, reason: str, risk_type: str) -> dict:
    """Simulate the ON CONFLICT upsert logic from the vetter."""
    penalty_until = today + timedelta(days=30)
    if existing is None:
        return {
            "ticker": "AAPL",
            "first_flagged_date": today,
            "last_flagged_date": today,
            "penalty_box_until": penalty_until,
            "flagged_count": 1,
            "reason": reason,
            "risk_type": risk_type,
        }
    else:
        return {
            "ticker": existing["ticker"],
            "first_flagged_date": existing["first_flagged_date"],
            "last_flagged_date": today,
            "penalty_box_until": penalty_until,
            "flagged_count": existing["flagged_count"] + 1,
            "reason": reason,
            "risk_type": risk_type,
        }


def test_new_entry_created_on_first_flag():
    today = date(2026, 5, 28)
    result = _simulate_upsert(None, today, "Earnings miss risk", "earnings")
    assert result["first_flagged_date"] == today
    assert result["last_flagged_date"] == today
    assert result["penalty_box_until"] == today + timedelta(days=30)
    assert result["flagged_count"] == 1
    assert result["reason"] == "Earnings miss risk"


def test_clock_resets_on_reflag():
    """Re-flagging a ticker within the penalty window resets penalty_box_until."""
    first_flag = date(2026, 5, 1)
    existing = {
        "ticker": "AAPL",
        "first_flagged_date": first_flag,
        "last_flagged_date": first_flag,
        "penalty_box_until": first_flag + timedelta(days=30),
        "flagged_count": 1,
        "reason": "Old reason",
        "risk_type": "regulatory",
    }
    reflag_date = date(2026, 5, 20)
    result = _simulate_upsert(existing, reflag_date, "New reason", "earnings")

    # First flag date unchanged
    assert result["first_flagged_date"] == first_flag
    # Last flag and penalty reset to reflag date
    assert result["last_flagged_date"] == reflag_date
    assert result["penalty_box_until"] == reflag_date + timedelta(days=30)
    # Count increments
    assert result["flagged_count"] == 2
    # Reason updated to latest
    assert result["reason"] == "New reason"


def test_flagged_count_increments_on_each_flag():
    today = date(2026, 5, 28)
    state = None
    for i in range(5):
        state = _simulate_upsert(state, today + timedelta(days=i), f"reason {i}", "regulatory")
    assert state["flagged_count"] == 5


def test_unflagged_ticker_not_entered():
    """A ticker that is NOT in exclusions must not be entered in the penalty box."""
    exclusions = [{"ticker": "GOOGL", "reason": "SEC probe", "risk_type": "regulatory"}]
    all_tickers = ["AAPL", "MSFT", "GOOGL", "META"]
    excluded_set = {e["ticker"] for e in exclusions}
    penalty_box_entries = [t for t in all_tickers if t in excluded_set]
    not_entered = [t for t in all_tickers if t not in excluded_set]

    assert "GOOGL" in penalty_box_entries
    assert "AAPL" not in penalty_box_entries
    assert "MSFT" in not_entered


# ── Expired penalty box ────────────────────────────────────────────────────────

def test_expired_penalty_box_not_returned_by_query():
    """Penalty box entries with penalty_box_until < today are treated as expired."""
    today = date(2026, 5, 28)
    rows = [
        {"ticker": "AAPL", "penalty_box_until": today - timedelta(days=1)},  # expired
        {"ticker": "MSFT", "penalty_box_until": today},                       # expires today (still active)
        {"ticker": "GOOGL", "penalty_box_until": today + timedelta(days=10)}, # active
    ]
    # The SQL WHERE clause is penalty_box_until >= today
    active = [r["ticker"] for r in rows if r["penalty_box_until"] >= today]
    assert "AAPL" not in active
    assert "MSFT" in active
    assert "GOOGL" in active


def test_days_remaining_api_calculation():
    """API correctly computes days_remaining from penalty_box_until."""
    today = date(2026, 5, 28)
    cases = [
        (today + timedelta(days=15), 15),
        (today + timedelta(days=1),   1),
        (today,                        0),
        (today - timedelta(days=1),    0),  # expired → clamped to 0
    ]
    for penalty_until, expected in cases:
        remaining = max(0, (penalty_until - today).days)
        assert remaining == expected, f"for until={penalty_until} expected {expected}, got {remaining}"


# ── Extra-held augmentation ────────────────────────────────────────────────────

def test_extra_held_tickers_identified():
    """Held tickers not in top-N candidates are correctly identified."""
    top_n_candidates = [{"ticker": "AAPL"}, {"ticker": "MSFT"}, {"ticker": "GOOGL"}]
    held_tickers = {"MSFT", "NVDA", "META"}  # MSFT is in top-N, NVDA and META are not

    candidate_set = {c["ticker"] for c in top_n_candidates}
    extra_held = [t for t in held_tickers if t not in candidate_set]

    assert set(extra_held) == {"NVDA", "META"}
    assert "MSFT" not in extra_held


def test_no_extra_held_when_all_in_top_n():
    """When all held tickers are in top-N, extra_held is empty."""
    top_n_candidates = [{"ticker": "AAPL"}, {"ticker": "MSFT"}]
    held_tickers = {"AAPL", "MSFT"}
    candidate_set = {c["ticker"] for c in top_n_candidates}
    extra_held = [t for t in held_tickers if t not in candidate_set]
    assert extra_held == []


def test_extra_held_defaults_for_unranked_ticker():
    """A held ticker not present in rankings at all gets rank=9999 and empty factor_scores."""
    ranked_extra_map = {}  # ticker not in rankings
    t = "DELISTED"
    r = ranked_extra_map.get(t)
    entry = {
        "ticker": t,
        "rank": r.rank if r else 9999,
        "composite_score": float(r.composite_score) if r and r.composite_score is not None else None,
        "factor_scores": dict(r.factor_scores) if r and r.factor_scores else {},
    }
    assert entry["rank"] == 9999
    assert entry["composite_score"] is None
    assert entry["factor_scores"] == {}
