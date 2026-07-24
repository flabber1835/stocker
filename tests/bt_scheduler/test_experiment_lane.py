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
