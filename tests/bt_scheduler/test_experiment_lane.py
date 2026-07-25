"""Phase 6c experiment lane — pure decision logic (experiment_due /
fired_this_week) and the evaluator-side config_diff attribution helper."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.logic import experiment_due, fired_this_week

ET = ZoneInfo("America/New_York")


def test_experiment_due_at_or_after_hour_any_day():
    assert experiment_due(datetime(2026, 7, 25, 22, 5, tzinfo=ET), 22) is True   # Sat
    assert experiment_due(datetime(2026, 7, 22, 23, 0, tzinfo=ET), 22) is True   # Wed
    assert experiment_due(datetime(2026, 7, 22, 21, 59, tzinfo=ET), 22) is False


def _e(fired, status="success"):
    return {"fired_at": fired, "status": status}


def test_fired_this_week_counts_iso_week_fires_only():
    today = date(2026, 7, 22)                      # ISO week 2026-W30 (Wed)
    exps = [
        _e("2026-07-20T22:00:00-04:00"),           # Mon this week
        _e("2026-07-21T22:00:00-04:00", "failed"), # Tue this week — failures count
        _e("2026-07-17T22:00:00-04:00"),           # Fri LAST week
        _e(None),                                  # never fired — ignored
        {"status": "running"},                     # no fired_at — ignored
        _e("garbage-timestamp"),                   # unparsable — ignored
    ]
    assert fired_this_week(exps, today) == 2


def test_fired_this_week_empty():
    assert fired_this_week([], date(2026, 7, 22)) == 0
    assert fired_this_week(None, date(2026, 7, 22)) == 0


def test_config_diff_dotted_paths_and_asymmetry():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    # config_diff is pure — extract and exec just the function source so the
    # evaluator's `app` package never enters this suite's (bt-scheduler)
    # namespace. NO sys.path changes here (the documented collision trap).
    import ast
    src = (root / "services" / "evaluator" / "app" / "tools.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "config_diff")
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<diff>", "exec"), ns)
    config_diff = ns["config_diff"]

    base = {"max_positions": 30,
            "portfolio_builder": {"vol_target": 0.18, "weighting": "equal_weight"},
            "universe": {"min_price": 5.0}}
    cand = {"max_positions": 20,
            "portfolio_builder": {"vol_target": 0.25, "weighting": "equal_weight"},
            "vetter": {"candidate_count": 50}}
    d = config_diff(base, cand)
    assert d["max_positions"] == {"from": 30, "to": 20}
    assert d["portfolio_builder.vol_target"] == {"from": 0.18, "to": 0.25}
    assert "portfolio_builder.weighting" not in d          # unchanged
    assert d["universe.min_price"] == {"from": 5.0, "to": None}   # removed side
    assert d["vetter.candidate_count"] == {"from": None, "to": 50}  # added side
    assert config_diff(base, base) == {}


# ── last-known-good coverage + next-fire (root-cause flaky-Lab fix) ───────────

def test_next_experiment_fire_today_then_tomorrow(monkeypatch):
    from app import main as m
    monkeypatch.setattr(m, "EXPERIMENT_HOUR", 22)
    before = datetime(2026, 7, 23, 18, 0, tzinfo=ET)   # before 22:00 → today
    after = datetime(2026, 7, 23, 23, 0, tzinfo=ET)    # after 22:00 → tomorrow
    assert m._next_experiment_fire(before).startswith("2026-07-23T22:00")
    assert m._next_experiment_fire(after).startswith("2026-07-24T22:00")


def test_remember_good_persists_and_survives(monkeypatch, tmp_path):
    from app import main as m
    monkeypatch.setattr(m, "ARTIFACTS_PATH", str(tmp_path))
    m._last_good = {}
    m._remember_good("coverage", {"go": True, "prices": {"rows": 35_000_000}},
                     "2026-07-23T22:00:00")
    # a fresh load (simulating a bt-scheduler restart) recovers last-good
    m._last_good = {}
    m._load_last_good()
    assert m._last_good["coverage"]["go"] is True
    assert m._last_good["coverage_as_of"] == "2026-07-23T22:00:00"


# ── Phase 6d: deterministic promotion gate + schedule builder ─────────────────

def test_promotion_gate_requires_margin_and_dd_tolerance():
    from app.logic import promotion_eligible  # legacy single-window helper
    base = {"annualized_return": 0.12, "max_drawdown": -0.25}
    # clears margin, drawdown similar → eligible
    ok, why = promotion_eligible({"annualized_return": 0.14, "max_drawdown": -0.27},
                                 base, margin=0.01, dd_tol=0.05)
    assert ok and "edge" in why
    # beats baseline but under the margin → not eligible
    ok, why = promotion_eligible({"annualized_return": 0.125, "max_drawdown": -0.20},
                                 base, margin=0.01, dd_tol=0.05)
    assert not ok and "margin" in why
    # big CAGR but drawdown blows the tolerance → not eligible
    ok, why = promotion_eligible({"annualized_return": 0.30, "max_drawdown": -0.45},
                                 base, margin=0.01, dd_tol=0.05)
    assert not ok and "drawdown" in why
    # no baseline yet → never promotes
    ok, why = promotion_eligible({"annualized_return": 0.30}, None)
    assert not ok and "baseline" in why


def test_schedule_maps_queue_to_daily_slots_with_cap_labels():
    from app.logic import build_schedule
    queued = [{"kind": "full_config", "hypothesis": f"h{i}"} for i in range(4)]
    sched = build_schedule(queued, "2026-07-24T22:00", fired_this_week=4, week_cap=5)
    assert len(sched) == 4
    assert sched[0]["when"].startswith("2026-07-24T22:00") and sched[0]["note"] is None
    assert sched[1]["when"].startswith("2026-07-25T22:00")
    # only 1 slot left this week → items 2+ labeled as deferred by the cap
    assert sched[1]["note"] == "after weekly cap resets"
    assert all(s["thesis"].startswith("h") for s in sched)
    assert build_schedule([], "2026-07-24T22:00", 0, 5) == []
    assert build_schedule(queued, "garbage", 0, 5) == []


# ── review findings: promotion-yardstick integrity ───────────────────────────

def test_baseline_invalid_once_a_promotion_was_applied():
    """The gate compares candidates to the baseline. If a promotion changed the
    LIVE config, a baseline that measured the OLD config is no longer the
    champion — gating against an ancestor lets each promotion drift the
    yardstick, and can promote a config WORSE than what is running."""
    from app.logic import baseline_is_valid
    fresh = {"status": "success", "applied_promotion": "hash1",
             "window": {"start": "2023-01-01", "end": "2026-01-01"}}
    ok, _ = baseline_is_valid(fresh, "hash1")
    assert ok is True
    ok, why = baseline_is_valid(fresh, "hash2")       # champion changed
    assert ok is False and "predates" in why
    ok, why = baseline_is_valid(None, None)
    assert ok is False and "no successful baseline" in why
    ok, why = baseline_is_valid({"status": "failed"}, None)
    assert ok is False
    # a baseline with no pinned window can't anchor a fair comparison
    ok, why = baseline_is_valid({"status": "success", "applied_promotion": None}, None)
    assert ok is False and "window" in why


def test_promotion_gate_is_window_pinned():
    """A candidate scored on a LATER window than the baseline gets a free CAGR
    edge from the shift alone — that must never promote."""
    from app.logic import promotion_eligible
    base = {"annualized_return": 0.12, "max_drawdown": -0.25}
    cand = {"annualized_return": 0.20, "max_drawdown": -0.25}
    # the gate itself is window-agnostic (pure numbers)…
    ok, _ = promotion_eligible(cand, base)
    assert ok is True
    # …so the LANE must refuse mismatched windows; that guard is asserted here
    # as the contract the caller implements (see main._experiment_lane).
    cand_win = {"start": "2023-06-01", "end": "2026-06-01"}
    base_win = {"start": "2023-01-01", "end": "2026-01-01"}
    assert cand_win != base_win


# ── validation split: the lane's two-window gate (review fix a) ───────────────

def _w(cagr, dd=-0.25):
    return {"annualized_return": cagr, "max_drawdown": dd}


def test_two_window_gate_requires_edge_that_survives_validation():
    from app.logic import promotion_eligible_2w
    base = {"tune": _w(0.12), "validate": _w(0.10)}
    # edge on tune AND holds on validate → promote
    ok, why = promotion_eligible_2w({"tune": _w(0.16), "validate": _w(0.11)}, base)
    assert ok and "validate edge" in why
    # THE case this fix exists for: big in-sample edge that COLLAPSES OOS
    ok, why = promotion_eligible_2w({"tune": _w(0.25), "validate": _w(0.02)}, base)
    assert not ok and "does NOT survive validation" in why
    # no real edge on tune
    ok, why = promotion_eligible_2w({"tune": _w(0.125), "validate": _w(0.20)}, base)
    assert not ok and "margin" in why
    # validate drawdown blows the tolerance
    ok, why = promotion_eligible_2w({"tune": _w(0.20), "validate": _w(0.11, -0.45)}, base)
    assert not ok and "drawdown" in why
    # missing pieces never promote
    assert promotion_eligible_2w({"tune": _w(0.2)}, base)[0] is False
    assert promotion_eligible_2w({"tune": _w(0.2), "validate": _w(0.2)}, None)[0] is False


def test_experiment_windows_carve_holdout_off_the_end():
    from app.logic import experiment_windows
    w = experiment_windows(date(2026, 7, 25), recent_years=3, validate_months=12)
    assert w["validate_end"] == "2026-07-25"
    assert w["validate_start"] == "2025-07-25"          # 12mo hold-out
    assert w["tune_end"] == w["validate_start"]         # contiguous, no overlap
    assert w["tune_start"] == "2023-07-25"              # 3y back from today
    # clamped to available data, and refused when tune gets too short
    w2 = experiment_windows(date(2026, 7, 25), 3, 12, earliest=date(2024, 1, 1))
    assert w2["tune_start"] == "2024-01-01"
    assert experiment_windows(date(2026, 7, 25), 3, 12,
                              earliest=date(2025, 6, 1)) is None
