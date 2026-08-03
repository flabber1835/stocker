"""Phase 6c experiment lane — pure decision logic (experiment_due /
fired_this_week) and the evaluator-side config_diff attribution helper."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.logic import experiment_due, fired_this_week

ET = ZoneInfo("America/New_York")


def test_experiment_due_at_or_after_hour_any_day():
    assert experiment_due(datetime(2026, 7, 25, 22, 5, tzinfo=ET), 22) is True   # Sat
    assert experiment_due(datetime(2026, 7, 22, 23, 0, tzinfo=ET), 22) is True   # Wed
    assert experiment_due(datetime(2026, 7, 22, 21, 59, tzinfo=ET), 22) is False


def _e(fired, status="success", kind="full_config"):
    return {"fired_at": fired, "status": status, "kind": kind}


def test_fired_this_week_counts_iso_week_fires_only():
    today = date(2026, 7, 22)                      # ISO week 2026-W30 (Wed)
    exps = [
        _e("2026-07-20T22:00:00-04:00"),           # Mon this week
        _e("2026-07-21T22:00:00-04:00", "failed"), # Tue this week — failures count
        _e("2026-07-17T22:00:00-04:00"),           # Fri LAST week
        _e(None),                                  # never fired — ignored
        {"status": "running", "kind": "full_config"},   # no fired_at — ignored
        _e("garbage-timestamp"),                   # unparsable — ignored
    ]
    assert fired_this_week(exps, today) == 2


def test_fired_this_week_empty():
    assert fired_this_week([], date(2026, 7, 22)) == 0
    assert fired_this_week(None, date(2026, 7, 22)) == 0


def test_baseline_fires_do_not_spend_the_weekly_candidate_budget():
    """The weekly cap bounds MULTIPLE TESTING against our one shared history. A
    baseline re-measures the config already live — no new hypothesis, no DSR to
    deflate — so it is not a draw. Counting it meant every yardstick re-run ate
    a candidate slot, and while the lane was re-firing the baseline daily (the
    windows-key bug) it burned the entire weekly budget on runs that tested
    nothing."""
    today = date(2026, 7, 25)                      # ISO week 2026-W30 (Sat)
    wasted = [_e("2026-07-22T22:00:00-04:00", kind="baseline"),
              _e("2026-07-23T22:00:00-04:00", kind="baseline"),
              _e("2026-07-24T22:00:00-04:00", kind="baseline")]
    assert fired_this_week(wasted, today) == 0, "baseline re-runs still eat slots"
    # …a real candidate still counts, and kinds=None restores the raw total
    mixed = wasted + [_e("2026-07-24T22:00:00-04:00")]
    assert fired_this_week(mixed, today) == 1
    assert fired_this_week(mixed, today, kinds=None) == 4


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
             "windows": _lane_windows(), "result": BASELINE_RESULT}
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


def _lane_windows() -> dict:
    """The window dict the lane really pins on an entry."""
    from datetime import date

    from app.logic import experiment_windows
    return experiment_windows(date(2026, 7, 25), 3, 12, date(2004, 1, 1))


def test_a_real_lane_baseline_entry_is_accepted():
    """REGRESSION (the loop-killer): baseline_is_valid read baseline['window']
    ['start'], but _experiment_lane pins baseline['windows'] = {tune_start,
    tune_end, validate_start, validate_end}. Every real baseline therefore read
    'no pinned comparison window', so the lane re-fired the YARDSTICK on every
    daily slot and never tested a single evaluator candidate — auto-promotion
    was inert in production while the unit test passed against an invented
    shape. This builds the entry the way the lane does, so the two can't drift
    apart again."""
    from app.logic import baseline_is_valid
    windows = _lane_windows()
    # verbatim from _experiment_lane's baseline branch + the completion write
    entry = {"id": "b1", "kind": "baseline", "hypothesis": "BASELINE: active config",
             "diff_vs_active": {}, "proposal_id": None, "windows": windows,
             "applied_promotion": None, "status": "success",
             "result": {"period_a": {"annualized_return": 0.1,
                                     "provenance": ENFORCED},
                        "period_b": {"annualized_return": 0.1,
                                     "provenance": ENFORCED}}}
    ok, why = baseline_is_valid(entry, None)
    assert ok is True, f"the lane's own baseline entry was rejected: {why}"
    # …and a candidate slot therefore opens instead of another baseline re-run
    for key in ("period_a_start", "period_a_end", "period_b_start", "period_b_end"):
        broken = {**entry, "windows": {k: v for k, v in windows.items() if k != key}}
        assert baseline_is_valid(broken, None)[0] is False


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

ENFORCED = {"parity_enforced": True, "coverage_enforced": True}
# A baseline needs a RESULT carrying gate provenance to be a usable yardstick —
# the promotion gate refuses any comparison whose baseline cannot show its gates
# were enforcing, so baseline_is_valid checks the same thing.
BASELINE_RESULT = {"period_a": {"annualized_return": 0.1, "provenance": ENFORCED},
                   "period_b": {"annualized_return": 0.1, "provenance": ENFORCED}}


def _w(cagr, dd=-0.25):
    # provenance is REQUIRED now: a summary without it cannot be vouched for and
    # the gate refuses it (see TestProvenanceGate).
    return {"annualized_return": cagr, "max_drawdown": dd, "provenance": ENFORCED}


def test_two_window_gate_requires_edge_that_survives_validation():
    from app.logic import promotion_eligible_2w
    base = {"period_a": _w(0.12), "period_b": _w(0.10)}
    # edge on tune AND holds on validate → promote
    ok, why = promotion_eligible_2w({"period_a": _w(0.16), "period_b": _w(0.11)}, base)
    assert ok and "period_b edge" in why
    # THE case this fix exists for: big in-sample edge that COLLAPSES OOS
    ok, why = promotion_eligible_2w({"period_a": _w(0.25), "period_b": _w(0.02)}, base)
    assert not ok and "does NOT persist into period_b" in why
    # no real edge on tune
    ok, why = promotion_eligible_2w({"period_a": _w(0.125), "period_b": _w(0.20)}, base)
    assert not ok and "margin" in why
    # validate drawdown blows the tolerance
    ok, why = promotion_eligible_2w({"period_a": _w(0.20), "period_b": _w(0.11, -0.45)}, base)
    assert not ok and "drawdown" in why
    # missing pieces never promote
    assert promotion_eligible_2w({"period_a": _w(0.2)}, base)[0] is False
    assert promotion_eligible_2w({"period_a": _w(0.2), "period_b": _w(0.2)}, None)[0] is False


def test_experiment_windows_carve_holdout_off_the_end():
    from app.logic import experiment_windows
    w = experiment_windows(date(2026, 7, 25), recent_years=3, validate_months=12)
    assert w["period_b_end"] == "2026-07-25"
    assert w["period_b_start"] == "2025-07-25"          # 12mo hold-out
    assert w["period_a_end"] == w["period_b_start"]         # contiguous, no overlap
    assert w["period_a_start"] == "2023-07-25"              # 3y back from today
    # clamped to available data, and refused when tune gets too short
    w2 = experiment_windows(date(2026, 7, 25), 3, 12, earliest=date(2024, 1, 1))
    assert w2["period_a_start"] == "2024-01-01"
    assert experiment_windows(date(2026, 7, 25), 3, 12,
                              earliest=date(2025, 6, 1)) is None


def test_candidate_is_scored_on_the_baselines_window_not_todays():
    """REGRESSION (the second loop-killer): experiment_windows is derived from
    `today`, and the lane recomputed it on every fire. One experiment runs per
    day, so a candidate fired the day after its baseline got a DIFFERENT window
    — and the gate's own precondition ('window mismatch vs baseline — not
    comparable') then refused EVERY promotion. Auto-promotion was structurally
    unreachable. Candidates must inherit the yardstick's exact windows."""
    from datetime import date

    from app.logic import baseline_is_valid, experiment_windows
    mon, tue = (experiment_windows(date(2026, 7, 20), 3, 12, date(2004, 1, 1)),
                experiment_windows(date(2026, 7, 21), 3, 12, date(2004, 1, 1)))
    assert mon != tue, "premise: the derived window shifts every day"

    baseline = {"kind": "baseline", "status": "success", "windows": mon,
                "applied_promotion": None, "result": BASELINE_RESULT}
    # the lane's fire-time decision, verbatim
    assert baseline_is_valid(baseline, None, today=date(2026, 7, 21))[0] is True
    windows = tue
    if baseline.get("windows"):
        windows = baseline["windows"]
    assert windows == mon, "candidate did not inherit the baseline's window"
    # …which is exactly what the gate compares before promoting
    assert baseline["windows"] == windows


def test_pinned_baseline_is_retired_once_its_window_ages():
    """Pinning keeps the comparison fair but freezes it in time — the yardstick
    has to be re-measured or candidates are forever judged against a stale era."""
    from datetime import date

    from app.logic import baseline_is_valid, experiment_windows
    w = experiment_windows(date(2026, 1, 10), 3, 12, date(2004, 1, 1))
    baseline = {"kind": "baseline", "status": "success", "windows": w,
                "applied_promotion": None, "result": BASELINE_RESULT}
    ok, _ = baseline_is_valid(baseline, None, today=date(2026, 2, 1), max_age_days=30)
    assert ok is True, "a three-week-old yardstick is still usable"
    ok, why = baseline_is_valid(baseline, None, today=date(2026, 3, 1), max_age_days=30)
    assert ok is False and "re-running the yardstick" in why
    # no `today` given → age is not judged (back-compat for pure callers)
    assert baseline_is_valid(baseline, None)[0] is True


# ── engine-busy visibility (the "UI said none running while CPU was 84%") ─────

def test_engine_busy_is_reported_for_a_sweep_the_lane_did_not_start():
    """_experiment_snapshot only asked the engine what it was doing when the
    LANE already believed one of its own experiments was running. A sweep
    started any other way — a manual POST, a leftover — left the Lab showing
    'none running' while bt-engine sat pegged at 84% CPU. That is the same
    blind spot that let three aborted nightly runs pass unnoticed for weeks:
    the strip described the lane's bookkeeping, never the machine."""
    import asyncio

    from app import main as m

    class _Resp:
        def __init__(self, payload): self._p = payload
        def json(self): return self._p

    class _Client:
        def __init__(self, sweep): self._sweep = sweep
        async def get(self, url):
            if url.endswith("/sweeps/latest"):
                return _Resp({"sweep": self._sweep})
            return _Resp({})

    foreign = {"sweep_id": "manual-1234-5678", "status": "running",
               "n_configs": 1, "progress_pct": 42, "started_at": "2026-07-25T12:00:00"}

    snap = asyncio.run(m._experiment_snapshot(
        _Client(foreign), datetime(2026, 7, 25, 13, 0, tzinfo=ET)))
    assert snap["running"] is None, "the lane owns no experiment here"
    eb = snap["engine_busy"]
    assert eb and eb["sweep_id"] == "manual-1234-5678"
    assert eb["owned_by_lane"] is False
    assert eb["progress_pct"] == 42


def test_engine_busy_is_none_when_the_engine_is_idle():
    import asyncio

    from app import main as m

    class _Resp:
        def __init__(self, payload): self._p = payload
        def json(self): return self._p

    class _Client:
        async def get(self, url):
            return _Resp({"sweep": {"sweep_id": "old", "status": "success"}})

    snap = asyncio.run(m._experiment_snapshot(
        _Client(), datetime(2026, 7, 25, 13, 0, tzinfo=ET)))
    assert snap["engine_busy"] is None


# ── named stress regimes (docs/architecture.md "named stress regimes") ────────

def test_regime_windows_are_fixed_and_split_into_two_spans():
    from datetime import date

    from app.logic import STRESS_REGIMES, regime_windows
    w, why = regime_windows("gfc_2008", date(2005, 1, 3))
    assert why == "ok"
    assert w == {"period_a_start": "2007-10-01", "period_a_end": "2008-10-01",
                 "period_b_start": "2008-10-01", "period_b_end": "2009-06-30"}
    # every regime must be well-formed: start < split < end, no overlap
    for name, spec in STRESS_REGIMES.items():
        s, sp, e = (date.fromisoformat(spec[k]) for k in ("start", "split", "end"))
        assert s < sp < e, f"{name} spans are not ordered"
        assert spec["stresses"], f"{name} has no stated failure mode"


def test_unknown_regime_is_refused_not_guessed():
    from app.logic import regime_windows
    w, why = regime_windows("financial_crisis", None)
    assert w is None and "unknown regime" in why


def test_regime_inside_the_factor_warmup_runway_is_refused():
    """A window starting before the 12-1 momentum + 200d SMA lookback has
    warmed up would silently measure a momentum-only composite — something
    other than the strategy."""
    from datetime import date

    from app.logic import regime_windows
    w, why = regime_windows("gfc_2008", date(2007, 6, 1))
    assert w is None and "warm-up" in why
    # …and is accepted once the data clears the runway
    assert regime_windows("gfc_2008", date(2006, 1, 1))[0] is not None


def test_a_regime_run_can_never_promote():
    """THE safety property. A regime's two spans are crash/recovery halves, not
    a tune/hold-out pair — comparing them through the gate would be meaningless,
    and letting one promote would apply a config selected on a hand-picked
    historical period."""
    import inspect

    from app import main as m
    src = inspect.getsource(m._experiment_lane)
    assert 'if e.get("regime"):' in src, "the gate no longer short-circuits regime runs"
    idx_regime = src.index('if e.get("regime"):')
    idx_gate = src.index("promotion_eligible_2w")
    assert idx_regime < idx_gate, "the regime check must precede the promotion gate"


# ── prediction scoring: hold the evaluator to its own numbers ────────────────

def test_score_prediction_measures_signed_bias():
    from app.logic import score_prediction
    base = {"period_a": {"annualized_return": 0.12}}
    # over-predicted: said +5pp, got +3pp
    s = score_prediction(0.05, {"period_a": {"annualized_return": 0.15}}, base)
    assert s["actual_edge"] == pytest.approx(0.03)
    assert s["error"] == pytest.approx(0.02)      # signed: positive = optimistic
    assert s["direction_correct"] is True
    # wrong direction entirely
    s = score_prediction(0.05, {"period_a": {"annualized_return": 0.10}}, base)
    assert s["actual_edge"] == pytest.approx(-0.02)
    assert s["direction_correct"] is False


def test_unscoreable_predictions_return_none():
    """No prediction, or no comparable baseline, must not fabricate a score."""
    from app.logic import score_prediction
    base = {"period_a": {"annualized_return": 0.12}}
    assert score_prediction(None, {"period_a": {"annualized_return": 0.15}}, base) is None
    assert score_prediction(0.05, {"period_a": {}}, base) is None
    assert score_prediction(0.05, {"period_a": {"annualized_return": 0.15}}, None) is None
    # a prediction of exactly zero has no direction to be right about
    assert score_prediction(0.0, {"period_a": {"annualized_return": 0.12}},
                            base)["direction_correct"] is None


def test_a_refused_candidate_is_still_a_scored_forecast():
    """Scoring must not depend on promotion — most candidates are refused, and
    those forecasts are exactly the ones worth learning from."""
    import inspect

    from app import main as m
    src = inspect.getsource(m._experiment_lane)
    i_pred, i_ok = src.index("score_prediction("), src.index('if ok and e.get("config")')
    assert i_pred < i_ok, "prediction scoring sits inside the promotion branch"


# ── left-tail guard in the promotion gate ────────────────────────────────────

def _tw(p5):
    return {"terminal_wealth": {"p5_multiple": p5}, "provenance": ENFORCED}


def test_gate_refuses_a_fat_left_tail_at_equal_cagr():
    """THE point of terminal-wealth distributions. Same CAGR edge, same realised
    max_drawdown — but a materially worse 5th-percentile terminal wealth. The
    old gate could not see this at all."""
    from app.logic import promotion_eligible_2w
    base_w = {"annualized_return": 0.12, "max_drawdown": -0.25, **_tw(0.95)}
    cand_t = {"annualized_return": 0.15, "max_drawdown": -0.25, **_tw(0.95)}
    fat = {"annualized_return": 0.15, "max_drawdown": -0.25, **_tw(0.70)}
    ok, why = promotion_eligible_2w({"period_a": cand_t, "period_b": fat},
                                    {"period_a": base_w, "period_b": base_w})
    assert ok is False and "left tail worse" in why


def test_gate_allows_an_equal_or_better_tail():
    from app.logic import promotion_eligible_2w
    base_w = {"annualized_return": 0.12, "max_drawdown": -0.25, **_tw(0.95)}
    good = {"annualized_return": 0.15, "max_drawdown": -0.25, **_tw(0.97)}
    ok, why = promotion_eligible_2w({"period_a": good, "period_b": good},
                                    {"period_a": base_w, "period_b": base_w})
    assert ok is True and "left tail acceptable" in why


def test_tail_guard_is_inert_on_results_without_a_distribution():
    """Older rows and regime runs carry no terminal_wealth. A newly added check
    must never silently block every promotion."""
    from app.logic import promotion_eligible_2w
    # No terminal_wealth (the point of this test) but gates ENFORCED — the two
    # checks are independent and the provenance rule must not mask the tail one.
    base_w = {"annualized_return": 0.12, "max_drawdown": -0.25,
              "provenance": ENFORCED}
    good = {"annualized_return": 0.15, "max_drawdown": -0.25,
            "provenance": ENFORCED}
    ok, why = promotion_eligible_2w({"period_a": good, "period_b": good},
                                    {"period_a": base_w, "period_b": base_w})
    assert ok is True and "check skipped" in why


def test_tail_guard_cannot_rescue_a_candidate_that_fails_an_earlier_condition():
    """Order matters: a spectacular tail must not paper over a missing edge."""
    from app.logic import promotion_eligible_2w
    base_w = {"annualized_return": 0.12, "max_drawdown": -0.25, **_tw(0.95)}
    weak = {"annualized_return": 0.121, "max_drawdown": -0.25, **_tw(1.50)}
    ok, why = promotion_eligible_2w({"period_a": weak, "period_b": weak},
                                    {"period_a": base_w, "period_b": base_w})
    assert ok is False and "margin" in why


def test_tail_tolerance_is_configurable():
    from app.logic import promotion_eligible_2w
    base_w = {"annualized_return": 0.12, "max_drawdown": -0.25, **_tw(0.95)}
    cand = {"annualized_return": 0.15, "max_drawdown": -0.25, **_tw(0.80)}
    args = ({"period_a": cand, "period_b": cand}, {"period_a": base_w, "period_b": base_w})
    assert promotion_eligible_2w(*args, tail_tol=0.05)[0] is False
    assert promotion_eligible_2w(*args, tail_tol=0.20)[0] is True


# ── period_a/period_b naming + the single engine translation ────────────────

def test_lane_windows_use_the_honest_period_names():
    """They were tune/validate, which oversold them: nothing is tuned. The
    baseline is the active config measured as-is and a candidate is authored
    from reasoning, not fitted to period A."""
    from datetime import date

    from app.logic import experiment_windows, regime_windows
    w = experiment_windows(date(2026, 7, 25), 3, 12, date(2004, 1, 1))
    assert set(w) == {"period_a_start", "period_a_end",
                      "period_b_start", "period_b_end"}
    r, _ = regime_windows("gfc_2008", date(2005, 1, 3))
    assert set(r) == set(w)


def test_engine_translation_is_exact_and_lossless():
    """bt-engine's request schema still speaks tune_*/validate_*. ONE mapping
    point keeps the misleading vocabulary out of everything a human or the
    evaluator reads, without renaming across a service boundary that has
    already produced one dead-loop bug from a key mismatch."""
    from datetime import date

    from app.logic import experiment_windows
    from app.main import _engine_window_keys
    w = experiment_windows(date(2026, 7, 25), 3, 12, date(2004, 1, 1))
    eng = _engine_window_keys(w)
    assert set(eng) == {"tune_start", "tune_end", "validate_start", "validate_end"}
    assert eng["tune_start"] == w["period_a_start"]
    assert eng["tune_end"] == w["period_a_end"]
    assert eng["validate_start"] == w["period_b_start"]
    assert eng["validate_end"] == w["period_b_end"]


def test_legacy_grid_windows_keep_the_engine_vocabulary():
    """derive_windows is splatted STRAIGHT into the /sweeps/run payload for the
    legacy grid, so it must NOT be renamed — doing so silently broke that path
    while every lane test stayed green."""
    from datetime import date

    from app.logic import derive_windows
    w = derive_windows({"tune_years": 6, "validate_years": 2}, date(2026, 7, 25),
                       date(2004, 1, 1))
    assert set(w) == {"tune_start", "tune_end", "validate_start", "validate_end"}


# ── gate provenance: a result must record the conditions that produced it ────

class TestProvenanceGate:
    """BT_PARITY_ENFORCE / BT_COVERAGE_ENFORCE exist so a safety gate can be
    flipped without an image rebuild. But a run produced with a gate DISABLED
    was byte-indistinguishable from a checked one, so the promotion gate —
    deterministic code that rewrites the live strategy — could accept a
    candidate scored under no parity check at all. A gate you can disable while
    its output still steers the live config is decorative."""

    def _pair(self, prov):
        w = {"annualized_return": 0.20, "max_drawdown": -0.25}
        if prov is not None:
            w = {**w, "provenance": prov}
        return {"period_a": w, "period_b": w}

    def _base(self, prov=None):
        w = {"annualized_return": 0.10, "max_drawdown": -0.25,
             "provenance": prov if prov is not None else ENFORCED}
        return {"period_a": w, "period_b": w}

    def test_an_otherwise_winning_candidate_is_refused_without_provenance(self):
        """+10pp of CAGR edge in both windows still loses to a missing stamp."""
        from app.logic import promotion_eligible_2w
        ok, why = promotion_eligible_2w(self._pair(None), self._base())
        assert ok is False and "no gate provenance" in why

    def test_parity_disabled_is_refused_and_named(self):
        from app.logic import promotion_eligible_2w
        ok, why = promotion_eligible_2w(
            self._pair({"parity_enforced": False, "coverage_enforced": True}),
            self._base())
        assert ok is False and "parity_enforced" in why

    def test_coverage_disabled_is_refused_and_named(self):
        from app.logic import promotion_eligible_2w
        ok, why = promotion_eligible_2w(
            self._pair({"parity_enforced": True, "coverage_enforced": False}),
            self._base())
        assert ok is False and "coverage_enforced" in why

    def test_an_unenforced_BASELINE_also_blocks(self):
        """The yardstick matters as much as the candidate: comparing against a
        baseline scored without the gates is the same defect one level down."""
        from app.logic import promotion_eligible_2w
        ok, why = promotion_eligible_2w(
            self._pair(ENFORCED),
            self._base({"parity_enforced": False, "coverage_enforced": True}))
        assert ok is False and "parity_enforced" in why

    def test_fully_enforced_results_still_promote(self):
        """The guard must not become a blanket refusal — otherwise the loop is
        dead and nobody notices for a month."""
        from app.logic import promotion_eligible_2w
        ok, why = promotion_eligible_2w(self._pair(ENFORCED), self._base())
        assert ok is True, why

    def test_provenance_is_checked_before_any_number_is_compared(self):
        """An unenforced result must be refused ON PROVENANCE, not accidentally
        by failing some other condition — otherwise a strong-looking unenforced
        candidate would be reported with a misleading reason."""
        from app.logic import promotion_eligible_2w
        ok, why = promotion_eligible_2w(self._pair(None), self._base())
        assert "margin" not in why and "drawdown" not in why


def test_provenance_helper_is_pure_and_defaults_closed():
    from app.logic import provenance_is_trustworthy
    assert provenance_is_trustworthy({}, {})[0] is False
    assert provenance_is_trustworthy({"provenance": {}})[0] is False
    assert provenance_is_trustworthy({"provenance": ENFORCED})[0] is True
    # A non-dict provenance (corrupt row) must not be truthy-accepted.
    assert provenance_is_trustworthy({"provenance": "yes"})[0] is False


def test_a_baseline_without_provenance_is_retired_so_the_lane_self_heals():
    """THE deadlock this closes. The promotion gate refuses any comparison whose
    BASELINE cannot show its gates were enforcing. If baseline_is_valid did not
    check the same thing, the lane would consider its yardstick fine, never
    re-run it, and refuse every candidate for a reason more candidates cannot
    fix — a loop that looks busy and can never promote."""
    from app.logic import baseline_is_valid
    windows = {"period_a_start": "2023-01-01", "period_a_end": "2024-01-01",
               "period_b_start": "2024-01-01", "period_b_end": "2025-01-01"}
    stale = {"status": "success", "applied_promotion": None, "windows": windows,
             "result": {"period_a": {"annualized_return": 0.1},
                        "period_b": {"annualized_return": 0.1}}}
    ok, why = baseline_is_valid(stale, None)
    assert ok is False and "provenance" in why
    assert "re-running the yardstick" in why, "must trigger a re-run, not just fail"

    fresh = {**stale, "result": {
        "period_a": {"annualized_return": 0.1, "provenance": ENFORCED},
        "period_b": {"annualized_return": 0.1, "provenance": ENFORCED}}}
    assert baseline_is_valid(fresh, None)[0] is True


def test_a_baseline_scored_with_a_gate_off_is_also_retired():
    from app.logic import baseline_is_valid
    windows = {"period_a_start": "2023-01-01", "period_a_end": "2024-01-01",
               "period_b_start": "2024-01-01", "period_b_end": "2025-01-01"}
    off = {"parity_enforced": False, "coverage_enforced": True}
    b = {"status": "success", "applied_promotion": None, "windows": windows,
         "result": {"period_a": {"annualized_return": 0.1, "provenance": off},
                    "period_b": {"annualized_return": 0.1, "provenance": off}}}
    ok, why = baseline_is_valid(b, None)
    assert ok is False and "parity_enforced" in why


def test_baseline_invalid_once_the_CONFIG_ITSELF_changed():
    """The promotion check missed the way the owner actually changes the
    strategy: a YAML edit + deploy. Nothing else retires the yardstick — not an
    edit, not a revert — so a baseline measured under an edited config stayed
    "valid" forever and every later candidate was gated against a config no
    longer running. Same ancestor-drift the promotion check exists to prevent,
    arriving by the manual route.

    The case that forced this: a config live for two DAYS during a one-off
    portfolio migration would have become the permanent promotion yardstick.
    """
    from app.logic import baseline_is_valid
    base = {"status": "success", "applied_promotion": None,
            "windows": _lane_windows(), "result": BASELINE_RESULT,
            "config_hash": "c9517f45ec9e90ad"}

    ok, _why = baseline_is_valid(base, None, active_config_hash="c9517f45ec9e90ad")
    assert ok is True, "same config must NOT churn a multi-hour yardstick run"

    ok, why = baseline_is_valid(base, None, active_config_hash="c5bc5d20824f85ae")
    assert ok is False
    assert "c9517f45ec9e90ad" in why and "c5bc5d20824f85ae" in why, (
        "the reason must name BOTH hashes — 'stale baseline' sends the reader "
        "hunting for which config it measured")


def test_an_unreadable_config_hash_FAILS_OPEN():
    """Either side missing means we could not read one, not that they differ.
    Retiring the yardstick on a probe timeout would throw away a multi-hour run
    for nothing, and would do it exactly when the engine is least healthy."""
    from app.logic import baseline_is_valid
    base = {"status": "success", "applied_promotion": None,
            "windows": _lane_windows(), "result": BASELINE_RESULT,
            "config_hash": "c9517f45ec9e90ad"}
    assert baseline_is_valid(base, None, active_config_hash=None)[0] is True
    assert baseline_is_valid({**base, "config_hash": None},
                             None, active_config_hash="whatever")[0] is True


def test_the_engine_reports_the_hash_the_check_needs():
    """The seam. bt-scheduler cannot read /strategies, so it asks the engine that
    would RUN the config. If /gates/check stops returning config_hash the check
    silently fails open forever — a guard that cannot fire."""
    import inspect

    from app import main as bt_main
    src = inspect.getsource(bt_main._experiment_lane)
    assert "/gates/check" in src and "config_hash" in src

    engine_src = open(os.path.join(
        os.path.dirname(__file__), "..", "..",
        "services", "bt-engine", "app", "main.py")).read()
    gates = engine_src[engine_src.index('@app.get("/gates/check")'):]
    gates = gates[:gates.index("@app.", 10)]
    assert '"config_hash"' in gates
