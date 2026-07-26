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

from stock_strategy_shared.wealth import (DEFAULT_TAIL_TOLERANCE,
                                          tail_is_acceptable)


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
    # ENGINE KEYS, deliberately: this dict is splatted straight into the
    # /sweeps/run payload for the legacy grid path, so it must speak bt-engine's
    # request vocabulary. The experiment lane's own windows use period_a/period_b
    # (see experiment_windows) and are translated at the call site.
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


CANDIDATE_KINDS = ("full_config",)


def fired_this_week(experiments: list[dict], today: date,
                    kinds: tuple[str, ...] | None = CANDIDATE_KINDS) -> int:
    """How many experiment-lane runs were FIRED in `today`'s ISO week (the
    weekly statistical budget). Counts fires, not completions — a failed run
    still spent a draw against the one shared history.

    Only CANDIDATE fires count by default. The cap exists to bound multiple
    testing against our one shared price history, and a BASELINE is not a draw:
    it re-measures the config already live, tests no new hypothesis and deflates
    no DSR. Counting it meant every yardstick re-run silently ate a candidate
    slot — and while the lane was re-firing the baseline daily (the windows-key
    bug) it burned the whole weekly budget on runs that tested nothing. Pass
    kinds=None to count every fire."""
    wk = today.isocalendar()[:2]
    n = 0
    for e in experiments or []:
        if kinds is not None and e.get("kind") not in kinds:
            continue
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


def score_prediction(predicted: float | None, cand: dict | None,
                     base: dict | None) -> dict | None:
    """Score the evaluator's committed CAGR-edge prediction against what the
    wind tunnel actually produced. Returns None when it cannot be scored
    (no prediction, or no comparable baseline). Pure.

    This is what makes the evaluator accountable on the same terms it holds the
    strategy to: it writes an expected_effect on every recommendation and, until
    now, nobody ever checked. Signed error (not absolute) is the point — the
    useful statistic is BIAS, i.e. whether it is systematically optimistic about
    its own ideas."""
    if predicted is None:
        return None
    ct, bt = (cand or {}).get("period_a"), (base or {}).get("period_a")
    if _cagr(ct) is None or _cagr(bt) is None:
        return None
    actual = _cagr(ct) - _cagr(bt)
    return {
        "predicted_edge": round(float(predicted), 6),
        "actual_edge": round(actual, 6),
        # signed: positive = the evaluator over-predicted its own edge
        "error": round(float(predicted) - actual, 6),
        "abs_error": round(abs(float(predicted) - actual), 6),
        # a prediction of exactly 0 has no direction to be right about
        "direction_correct": bool(predicted * actual > 0) if predicted else None,
    }


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
    # The pinned window is `windows` (period_a_start/period_a_end/
    # period_b_start/period_b_end) — EXACTLY the dict _experiment_lane stores and
    # compares for window-equality before gating. This used to read a
    # non-existent baseline["window"]["start"], so EVERY real baseline was
    # judged unpinned: the lane re-fired the yardstick on every daily slot and
    # no evaluator candidate was ever tested — the whole auto-promotion loop
    # was inert in production while the unit test passed against a made-up
    # shape. Keep this key list identical to what the lane writes.
    windows = baseline.get("windows") or {}
    if not all(windows.get(k) for k in
               ("period_a_start", "period_a_end", "period_b_start", "period_b_end")):
        return False, "baseline has no pinned comparison window"
    # Candidates are scored on the BASELINE's windows (experiment_windows is
    # derived from `today`, so recomputing them per fire made every candidate
    # land on a different window than the yardstick — the gate's own
    # window-equality precondition then refused every promotion). Pinning means
    # the window ages, so retire the yardstick once it does and re-measure.
    if today is not None:
        try:
            ve = date.fromisoformat(str(windows["period_b_end"]))
        except (TypeError, ValueError):
            return False, "baseline period_b_end unparseable"
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
    """Split the recent era into PERIOD A (earlier) + PERIOD B (later hold-out).

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
    return {"period_a_start": tune_start.isoformat(),
            "period_a_end": tune_end.isoformat(),
            "period_b_start": validate_start.isoformat(),
            "period_b_end": validate_end.isoformat()}


# ── Named stress regimes (docs/architecture.md "named stress regimes") ───────
# A FIXED, pre-registered set. The evaluator requests a regime by NAME and can
# never supply raw dates: the DSR machinery deflates for how many CONFIGS were
# tried, not how many PERIODS, so a model free to choose both searches two
# dimensions while penalised on one. Each entry targets a DISTINCT failure mode.
#
# `split` cuts the window into two NON-overlapping spans carried as the existing
# tune/validate fields. They are NOT a tune/hold-out pair — a regime run can
# never promote (see _experiment_lane) — they are crash-then-recovery halves.
STRESS_REGIMES: dict[str, dict] = {
    "gfc_2008": {
        "start": "2007-10-01", "split": "2008-10-01", "end": "2009-06-30",
        "stresses": "credit crisis, -55% market, and the March-2009 momentum "
                    "crash — the worst episode in history for a momentum book",
    },
    "covid_2020": {
        "start": "2020-01-02", "split": "2020-04-01", "end": "2020-09-30",
        "stresses": "fastest -34% on record then a V — maximally adverse for a "
                    "drawdown veto, which sells the bottom and blocks re-entry",
    },
    "bear_2022": {
        "start": "2022-01-03", "split": "2022-07-01", "end": "2023-01-31",
        "stresses": "rate-shock grind and growth->value rotation; a slow bleed "
                    "rather than a crash, so it tests rotation not survival",
    },
    "energy_shock_2015": {
        "start": "2015-06-01", "split": "2015-12-01", "end": "2016-03-31",
        "stresses": "oil -70% sector blowup — sector-concentration risk",
    },
    "volmageddon_2018": {
        "start": "2018-01-02", "split": "2018-10-01", "end": "2019-01-31",
        "stresses": "Feb-2018 vol spike plus the Q4 drawdown; tests "
                    "low_volatility and the vol-scaled falling-knife threshold",
    },
}

# Factor warm-up the sim needs before a window can mean anything: 12-1 momentum
# (~252 sessions) plus the 200-day regime SMA, with slack. A regime starting
# inside this runway would silently produce a momentum-only composite.
REGIME_WARMUP_DAYS = 400


def regime_windows(name: str, earliest: date | None = None
                   ) -> tuple[dict | None, str]:
    """Fixed windows for a named stress regime, or (None, reason).

    `earliest` is the earliest viable data start from bt-data coverage; a regime
    whose start does not clear it by REGIME_WARMUP_DAYS is REFUSED rather than
    run on a half-warm factor set. Pure."""
    spec = STRESS_REGIMES.get(str(name or ""))
    if not spec:
        return None, (f"unknown regime {name!r} — choose one of "
                      f"{', '.join(sorted(STRESS_REGIMES))}")
    start = date.fromisoformat(spec["start"])
    if earliest is not None and (start - earliest).days < REGIME_WARMUP_DAYS:
        return None, (f"regime {name} starts {start} but data only begins "
                      f"{earliest}; needs {REGIME_WARMUP_DAYS}d of factor "
                      "warm-up (12-1 momentum + 200d regime SMA)")
    return {"period_a_start": spec["start"], "period_a_end": spec["split"],
            "period_b_start": spec["split"], "period_b_end": spec["end"]}, "ok"


def _cagr(summary: dict | None) -> float | None:
    if not summary:
        return None
    v = summary.get("annualized_return")
    return None if v is None else float(v)


REQUIRED_GATES = ("parity_enforced", "coverage_enforced")


def provenance_is_trustworthy(*summaries) -> tuple[bool, str]:
    """Were the safety gates enforcing when EVERY compared summary was produced?

    Pure. A gate that can be switched off while its output still steers the live
    config is decorative — so a run made with parity or coverage disabled must be
    non-promotable, not merely unverified. Absent provenance is treated as NOT
    enforced: a row that predates the stamp is precisely the one that cannot be
    vouched for, and the failure direction for a rule that rewrites the live
    strategy is 'refuse'."""
    for s in summaries:
        prov = (s or {}).get("provenance")
        if not isinstance(prov, dict):
            return False, ("result carries no gate provenance — cannot confirm "
                           "the parity/coverage gates were enforcing when it was "
                           "produced (re-run it under the current engine)")
        off = [g for g in REQUIRED_GATES if not prov.get(g)]
        if off:
            return False, (f"produced with {', '.join(off)}=false — a result "
                           "scored with a safety gate disabled is not promotable")
    return True, "gates enforced"


def promotion_eligible_2w(cand: dict | None, base: dict | None,
                          margin: float = 0.01, dd_tol: float = 0.05,
                          validate_tol: float = 0.0,
                          tail_tol: float = DEFAULT_TAIL_TOLERANCE
                          ) -> tuple[bool, str]:
    """Two-window promotion gate. `cand`/`base` are {"period_a": summary,
    "period_b": summary} from ONE sweep job each (same windows by construction).

    NAMING: these were called tune/validate, which oversold them. NOTHING is
    tuned — the baseline is the active config measured as-is, and a candidate is
    authored by the evaluator from reasoning and the packet, not fitted to
    period A. What the split actually buys is STABILITY: the edge must appear in
    two different spans, not just one. (Nor is it a true hold-out — the model has
    read all of market history; the shadow challenger is the honest verdict and
    this is the cheap pre-filter.) For a stress regime the two spans are
    crash/recovery halves instead of earlier/later.

    Promote only when the candidate:
      1. beats the baseline's TUNE CAGR by >= margin  (there is a real edge)
      2. is not worse than the baseline's VALIDATE CAGR by more than
         validate_tol                                  (the edge survives OOS)
      3. does not blow past the baseline's VALIDATE drawdown by dd_tol
    Pure — the LLM authors candidates, this decides."""
    ct, cv = (cand or {}).get("period_a"), (cand or {}).get("period_b")
    bt, bv = (base or {}).get("period_a"), (base or {}).get("period_b")
    if _cagr(ct) is None or _cagr(cv) is None:
        return False, "candidate missing period_a/period_b result"
    if _cagr(bt) is None or _cagr(bv) is None:
        return False, "no two-window baseline to compare against"
    # 0. PROVENANCE, before any number is compared. A result produced with the
    # parity or coverage gate DISABLED is byte-indistinguishable from a checked
    # one, so promotion has to read the stamp rather than the returns. Missing
    # provenance counts as NOT enforced: an older row is exactly the case that
    # cannot be vouched for, and this rule rewrites the live config.
    prov_ok, prov_why = provenance_is_trustworthy(ct, cv, bt, bv)
    if not prov_ok:
        return False, prov_why

    edge = _cagr(ct) - _cagr(bt)
    if edge < margin:
        return False, f"period_a CAGR edge {edge:+.4f} < margin {margin:+.4f}"
    v_edge = _cagr(cv) - _cagr(bv)
    if v_edge < -validate_tol:
        return False, (f"edge does NOT persist into period_b: CAGR "
                       f"{v_edge:+.4f} vs baseline (tol {validate_tol:.4f})")
    cdd, bdd = (cv or {}).get("max_drawdown"), (bv or {}).get("max_drawdown")
    if cdd is not None and bdd is not None and float(cdd) < float(bdd) - dd_tol:
        return False, (f"period_b drawdown {float(cdd):.2%} worse than baseline "
                       f"{float(bdd):.2%} beyond {dd_tol:.0%}")
    # 4. LEFT TAIL. max_drawdown is one realised number from the single path
    # history happened to take; a candidate carrying a fat tail that simply did
    # not fire looks identical to a safe one. The bootstrapped 5th-percentile
    # terminal wealth is that risk measured directly, in the objective's own
    # units. Inert when either side lacks the distribution (older rows, regime
    # runs) — a new check must never silently block every promotion.
    tail_ok, tail_why = tail_is_acceptable((cv or {}).get("terminal_wealth"),
                                           (bv or {}).get("terminal_wealth"),
                                           tail_tol)
    if not tail_ok:
        return False, tail_why
    return True, (f"period_a edge {edge:+.4f} >= {margin:+.4f} AND period_b edge "
                  f"{v_edge:+.4f} holds (drawdown within {dd_tol:.0%}; "
                  f"{tail_why})")
