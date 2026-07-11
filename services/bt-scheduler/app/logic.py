"""bt-scheduler decision logic — PURE (no HTTP/DB/clock), so the automation's
due-ness rules are unit-testable. main.py owns I/O and the tick loop.

Automation contract (plan "Phase 6"):
  - daily TOPUP on weekdays after TOPUP_HOUR local (Sharadar publishes evenings)
  - one STANDING SWEEP per ISO week, fired on SWEEP_WEEKDAY >= SWEEP_HOUR, using
    the versioned spec in sweeps/standing_sweep.json with RELATIVE windows
    (tune_years / validate_years anchored to today) so the spec never goes stale
  - RESULTS BRIDGE: after a sweep completes, export the leaderboard artifact the
    live evaluator's packet reads (artifacts/bt/latest_sweep.json)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def derive_windows(spec: dict, today: date,
                   earliest_viable_start: date | None = None) -> dict | None:
    """Relative spec → concrete walk-forward windows anchored at `today`.
    tune: [today − (tune+validate)y, today − validate_y); validate: [that, today].
    Clamped to earliest_viable_start; returns None when the clamped tune window is
    too short (< 180 days) to be worth running."""
    v_years = float(spec.get("validate_years", 2))
    t_years = float(spec.get("tune_years", 6))
    validate_end = today
    validate_start = today - timedelta(days=int(v_years * 365.25))
    tune_end = validate_start
    tune_start = tune_end - timedelta(days=int(t_years * 365.25))
    if earliest_viable_start and tune_start < earliest_viable_start:
        tune_start = earliest_viable_start
    if (tune_end - tune_start).days < 180:
        return None
    return {"tune_start": tune_start.isoformat(), "tune_end": tune_end.isoformat(),
            "validate_start": validate_start.isoformat(),
            "validate_end": validate_end.isoformat()}


def topup_due(now_local: datetime, last_success_date: date | None,
              hour: int = 23) -> bool:
    """Weekday, past the publish hour, and no successful fetch yet today."""
    if now_local.weekday() >= 5 or now_local.hour < hour:
        return False
    return last_success_date is None or last_success_date < now_local.date()


def sweep_due(now_local: datetime, latest_sweep: dict | None,
              weekday: int = 5, hour: int = 2) -> bool:
    """One standing sweep per ISO week, fired on `weekday` (Mon=0) at/after
    `hour`. Never while one is running; a failed sweep this week is NOT retried
    automatically (a deterministic failure would loop — human looks instead)."""
    if now_local.weekday() != weekday or now_local.hour < hour:
        return False
    if latest_sweep is None:
        return True
    if latest_sweep.get("status") == "running":
        return False
    started = latest_sweep.get("started_at")
    if not started:
        return True
    started_d = datetime.fromisoformat(str(started).replace("Z", "+00:00")).date()
    return started_d.isocalendar()[:2] < now_local.date().isocalendar()[:2]


def artifact_needed(latest_sweep: dict | None, artifact: dict | None) -> bool:
    """Export when a COMPLETED sweep isn't the one already exported."""
    if not latest_sweep or latest_sweep.get("status") != "success":
        return False
    if artifact is None:
        return True
    return artifact.get("sweep_id") != latest_sweep.get("sweep_id")
