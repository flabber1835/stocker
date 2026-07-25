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


def sweep_needed(spec_hash: str, state: dict | None, n_pending_proposals: int,
                 today: date, force_refresh_days: int = 28) -> tuple[bool, str]:
    """Skip-if-unchanged gate (Phase 6b), applied ON TOP of sweep_due's weekly
    window: re-firing an identical sweep only adds one week of OOS data, so on
    the due day we actually fire only when there is something new to learn —
    the spec changed, evaluator proposals are waiting, or the periodic forced
    refresh (which keeps the relative windows sliding) is due. `state` is the
    persisted fire-state (artifacts/bt/sweep_state.json): last_spec_hash +
    last_fired_at; None = never fired."""
    if state is None or state.get("last_spec_hash") != spec_hash:
        return True, "spec changed" if state is not None else "first run"
    if n_pending_proposals > 0:
        return True, f"{n_pending_proposals} pending proposal(s)"
    last_fired = state.get("last_fired_at")
    if not last_fired:
        return True, "no prior fire recorded"
    try:
        fired_d = datetime.fromisoformat(str(last_fired)).date()
    except ValueError:
        return True, "unreadable fire-state"
    if (today - fired_d).days >= force_refresh_days:
        return True, f"forced refresh ({(today - fired_d).days}d since last fire)"
    return False, ("unchanged spec, no pending proposals, refresh not due "
                   f"({(today - fired_d).days}d/{force_refresh_days}d)")


def artifact_needed(latest_sweep: dict | None, artifact: dict | None) -> bool:
    """Export when a COMPLETED sweep isn't the one already exported."""
    if not latest_sweep or latest_sweep.get("status") != "success":
        return False
    if artifact is None:
        return True
    return artifact.get("sweep_id") != latest_sweep.get("sweep_id")


def experiment_due(now_local: datetime, hour: int = 22) -> bool:
    """Phase 6c daily experiment slot: any day, at/after `hour` local (default
    22 ET = 7pm PT, after the nightly topup window opens). The weekly cap and
    one-at-a-time rule are enforced by the caller."""
    return now_local.hour >= hour


def fired_this_week(experiments: list[dict], today: date) -> int:
    """How many experiment-lane runs were FIRED in `today`'s ISO week (the
    weekly statistical budget). Counts fires, not completions — a failed run
    still spent a draw against the one shared history."""
    wk = today.isocalendar()[:2]
    n = 0
    for e in experiments or []:
        fired = e.get("fired_at")
        if not fired:
            continue
        try:
            d = datetime.fromisoformat(str(fired)).date()
        except ValueError:
            continue
        if d.isocalendar()[:2] == wk:
            n += 1
    return n


def promotion_eligible(cand: dict | None, base: dict | None,
                       margin: float = 0.01, dd_tol: float = 0.05
                       ) -> tuple[bool, str]:
    """Phase 6d deterministic promotion gate: a candidate auto-promotes only if
    its recent-window CAGR beats the recent-window BASELINE (active config) by
    ≥ margin AND its max drawdown is not worse than the baseline's by more than
    dd_tol. Pure; the LLM never decides promotion — it only authors candidates."""
    if not cand or cand.get("annualized_return") is None:
        return False, "no candidate result"
    if not base or base.get("annualized_return") is None:
        return False, "no recent-window baseline to compare against"
    edge = float(cand["annualized_return"]) - float(base["annualized_return"])
    if edge < margin:
        return False, f"CAGR edge {edge:+.4f} < required margin {margin:+.4f}"
    cdd, bdd = cand.get("max_drawdown"), base.get("max_drawdown")
    if cdd is not None and bdd is not None and float(cdd) < float(bdd) - dd_tol:
        return False, (f"max drawdown {float(cdd):.2%} worse than baseline "
                       f"{float(bdd):.2%} beyond tolerance {dd_tol:.0%}")
    return True, (f"CAGR edge {edge:+.4f} ≥ {margin:+.4f}, drawdown within "
                  f"{dd_tol:.0%} of baseline")


def build_schedule(queued: list[dict], next_fire_iso: str,
                   fired_this_week: int, week_cap: int,
                   max_items: int = 8) -> list[dict]:
    """Map the queued experiments onto their expected firing slots (one per
    day, in queue order, starting at the next daily slot). Items beyond this
    ISO week's remaining budget are labeled — the cap defers them, order kept.
    Pure; approximation is honest (labels, no fake precision)."""
    try:
        fire = datetime.fromisoformat(next_fire_iso)
    except ValueError:
        return []
    budget = max(0, week_cap - fired_this_week)
    out = []
    for i, q in enumerate((queued or [])[:max_items]):
        out.append({
            "when": (fire + timedelta(days=i)).isoformat(timespec="minutes"),
            "kind": q.get("kind", "single_field"),
            "thesis": q.get("hypothesis") or "—",
            "note": None if i < budget else "after weekly cap resets",
        })
    return out


def baseline_is_valid(baseline: dict | None, applied_promotion_hash: str | None,
                      today: date | None = None, max_age_days: int = 30
                      ) -> tuple[bool, str]:
    """The promotion yardstick must measure the CURRENT champion. A baseline is
    stale once a promotion has actually been APPLIED live since it ran —
    otherwise every later candidate is gated against an ancestor config, and
    each promotion drifts the yardstick further from what is really running
    (a ratchet that can promote a config WORSE than the live one). Pure."""
    if not baseline or baseline.get("status") != "success":
        return False, "no successful baseline"
    if baseline.get("applied_promotion") != applied_promotion_hash:
        return False, ("baseline predates the live config (promotion "
                       f"{applied_promotion_hash}) — re-running the yardstick")
    # The pinned window is `windows` (tune_start/tune_end/validate_start/
    # validate_end) — EXACTLY the dict _experiment_lane stores on the entry and
    # compares for window-equality before gating. This used to read a
    # non-existent baseline["window"]["start"], so EVERY real baseline was
    # judged unpinned: the lane re-fired the yardstick on every daily slot and
    # no evaluator candidate was ever tested — the whole auto-promotion loop
    # was inert in production while the unit test passed against a made-up
    # shape. Keep this key list identical to what the lane writes.
    windows = baseline.get("windows") or {}
    if not all(windows.get(k) for k in
               ("tune_start", "tune_end", "validate_start", "validate_end")):
        return False, "baseline has no pinned comparison window"
    # Candidates are scored on the BASELINE's windows (experiment_windows is
    # derived from `today`, so recomputing them per fire made every candidate
    # land on a different window than the yardstick — the gate's own
    # window-equality precondition then refused every promotion). Pinning means
    # the window ages, so retire the yardstick once it does and re-measure.
    if today is not None:
        try:
            ve = date.fromisoformat(str(windows["validate_end"]))
        except (TypeError, ValueError):
            return False, "baseline validate_end unparseable"
        if (today - ve).days > max_age_days:
            return False, (f"baseline window ends {ve} ({(today - ve).days}d ago) "
                           f"— past {max_age_days}d, re-running the yardstick")
    return True, "baseline current"


def shift_months(d: date, months: int) -> date:
    """Calendar-month shift with day-of-month clamping. Local copy: bt-scheduler
    must not import from bt-engine (separate services/images)."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = (nxt - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def experiment_windows(today: date, recent_years: float, validate_months: int,
                       earliest: date | None = None) -> dict | None:
    """Split the recent era into TUNE + VALIDATE for the experiment lane.

    The lane used to score a candidate on the SAME window the evaluator was
    looking at when it authored the config — in-sample selection with an
    auto-apply attached. We now carve the most recent `validate_months` off the
    end as a hold-out: the candidate must earn its edge on tune AND still hold
    up on validate. (Nothing an LLM authors is ever truly out-of-sample — it has
    seen all history — so the shadow challenger's live-forward measurement
    remains the honest verdict; this is the cheap pre-filter.)

    Returns None when the derived tune window is too short to mean anything.
    """
    validate_end = today
    validate_start = shift_months(today, -int(validate_months))
    tune_end = validate_start
    tune_start = shift_months(validate_end, -int(round(recent_years * 12)))
    if earliest and tune_start < earliest:
        tune_start = earliest
    if (tune_end - tune_start).days < 180:
        return None
    return {"tune_start": tune_start.isoformat(), "tune_end": tune_end.isoformat(),
            "validate_start": validate_start.isoformat(),
            "validate_end": validate_end.isoformat()}


def _cagr(summary: dict | None) -> float | None:
    if not summary:
        return None
    v = summary.get("annualized_return")
    return None if v is None else float(v)


def promotion_eligible_2w(cand: dict | None, base: dict | None,
                          margin: float = 0.01, dd_tol: float = 0.05,
                          validate_tol: float = 0.0) -> tuple[bool, str]:
    """Two-window promotion gate. `cand`/`base` are {"tune": summary,
    "validate": summary} from ONE sweep job each (same windows by construction).

    Promote only when the candidate:
      1. beats the baseline's TUNE CAGR by >= margin  (there is a real edge)
      2. is not worse than the baseline's VALIDATE CAGR by more than
         validate_tol                                  (the edge survives OOS)
      3. does not blow past the baseline's VALIDATE drawdown by dd_tol
    Pure — the LLM authors candidates, this decides."""
    ct, cv = (cand or {}).get("tune"), (cand or {}).get("validate")
    bt, bv = (base or {}).get("tune"), (base or {}).get("validate")
    if _cagr(ct) is None or _cagr(cv) is None:
        return False, "candidate missing tune/validate result"
    if _cagr(bt) is None or _cagr(bv) is None:
        return False, "no two-window baseline to compare against"

    edge = _cagr(ct) - _cagr(bt)
    if edge < margin:
        return False, f"tune CAGR edge {edge:+.4f} < margin {margin:+.4f}"
    v_edge = _cagr(cv) - _cagr(bv)
    if v_edge < -validate_tol:
        return False, (f"edge does NOT survive validation: out-of-sample CAGR "
                       f"{v_edge:+.4f} vs baseline (tol {validate_tol:.4f})")
    cdd, bdd = (cv or {}).get("max_drawdown"), (bv or {}).get("max_drawdown")
    if cdd is not None and bdd is not None and float(cdd) < float(bdd) - dd_tol:
        return False, (f"validate drawdown {float(cdd):.2%} worse than baseline "
                       f"{float(bdd):.2%} beyond {dd_tol:.0%}")
    return True, (f"tune edge {edge:+.4f} >= {margin:+.4f} AND validate edge "
                  f"{v_edge:+.4f} holds (drawdown within {dd_tol:.0%})")
