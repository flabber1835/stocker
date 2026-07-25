"""bt-scheduler — automation for the backtest stack (backtest machine only).

Tick loop (BT_SCHED_TICK_SECS): daily Sharadar topup, weekly standing sweep from
the versioned spec (sweeps/standing_sweep.json, relative windows), and the
results bridge — exporting the latest completed sweep's leaderboard to
artifacts/bt/latest_sweep.json, which the LIVE evaluator's packet reads
(co-located: shared ./artifacts mount; separate machines: any file transport).

Phase 6b: the sweep is SKIP-IF-UNCHANGED (fires on the due day only when the
spec hash changed, evaluator proposals are pending, or the periodic forced
refresh is due — sweep_needed in logic.py; fire-state persists in
artifacts/bt/sweep_state.json), and the EXPERIMENT QUEUE
(artifacts/bt/proposals.json, written by the live evaluator) rides each sweep
as extra single-diff configs: pending → testing at fire, → tested at export,
with matching leaderboard rows tagged proposal=true.

The bridge is per-file one-way — no network path between the stacks, preserving
the isolation decision. Decision logic is pure (app/logic.py); this file is I/O.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

from app.logic import (artifact_needed, baseline_is_valid, build_schedule,
                       derive_windows, experiment_due, experiment_windows,
                       fired_this_week, promotion_eligible_2w, regime_windows,
                       score_prediction,
                       sweep_due, sweep_needed, topup_due)

BT_DATA_URL = os.getenv("BT_DATA_URL", "http://bt-data:8000")
BT_ENGINE_URL = os.getenv("BT_ENGINE_URL", "http://bt-engine:8000")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "/artifacts")
SPEC_PATH = os.getenv("STANDING_SWEEP_SPEC", "/sweeps/standing_sweep.json")
TICK_SECS = float(os.getenv("BT_SCHED_TICK_SECS", "300"))
TOPUP_HOUR = int(os.getenv("BT_TOPUP_HOUR", "23"))
SWEEP_WEEKDAY = int(os.getenv("BT_SWEEP_WEEKDAY", "4"))   # Mon=0 … Fri=4: sweep runs Fri evening,
                                                          # exporting BEFORE the Sat ~00-01 ET weekend review
SWEEP_HOUR = int(os.getenv("BT_SWEEP_HOUR", "19"))
FORCE_REFRESH_DAYS = int(os.getenv("BT_SWEEP_FORCE_REFRESH_DAYS", "28"))
# Phase 6c experiment lane: daily slot for evaluator-authored FULL-CONFIG
# candidates (+ the one-time auto-baseline of the active config), one at a
# time, capped per ISO week. 22 ET = 7pm PT (owner cadence).
EXPERIMENT_HOUR = int(os.getenv("BT_EXPERIMENT_HOUR", "22"))
EXPERIMENTS_PER_WEEK = int(os.getenv("BT_EXPERIMENTS_PER_WEEK", "5"))
EXPERIMENT_REBALANCE_EVERY = int(os.getenv("BT_EXPERIMENT_REBALANCE_EVERY", "5"))
# Phase 6d: experiments run over the RECENT window (owner philosophy: judge on
# the current era) — also what fits the bt-engine 4g memory cap. Full-history
# floor returns once the memory-lean loader lands.
EXPERIMENT_RECENT_YEARS = float(os.getenv("BT_EXPERIMENT_RECENT_YEARS", "3"))
# Deterministic auto-promotion gate (paper mode — see architecture.md 6d):
PROMOTE_MARGIN = float(os.getenv("BT_PROMOTE_MARGIN", "0.01"))         # +1pp CAGR
PROMOTE_DD_TOLERANCE = float(os.getenv("BT_PROMOTE_DD_TOLERANCE", "0.05"))
# Hold-out slice carved off the END of the recent window; a candidate must
# keep its edge here, not just on the data it was selected against.
EXPERIMENT_VALIDATE_MONTHS = int(os.getenv("BT_EXPERIMENT_VALIDATE_MONTHS", "12"))
PROMOTE_VALIDATE_TOL = float(os.getenv("BT_PROMOTE_VALIDATE_TOL", "0.0"))
# Left-tail guard: how much worse the candidate's 5th-percentile TERMINAL WEALTH
# may be than the baseline's, as a multiple of starting capital. CAGR and a
# single realised drawdown cannot see a tail that did not happen to fire.
PROMOTE_TAIL_TOLERANCE = float(os.getenv("BT_PROMOTE_TAIL_TOLERANCE", "0.05"))
# Candidates are scored on the BASELINE's exact windows (the gate refuses to
# compare across windows). That pins the comparison but lets it age, so the
# yardstick is re-measured once its validate window ends more than this many
# days ago — trading a rerun slot for a current comparison.
BASELINE_MAX_AGE_DAYS = int(os.getenv("BT_BASELINE_MAX_AGE_DAYS", "30"))
# Legacy Phase-5 weekly GRID: retired by default — the experiment lane is now
# the single driver and carries evaluator proposals itself. true re-enables.
STANDING_SWEEP_ENABLED = os.getenv("BT_STANDING_SWEEP_ENABLED", "false").lower() in ("1", "true", "yes")
LOCAL_TZ = ZoneInfo(os.getenv("SCHEDULE_TZ", "America/New_York"))

_status: dict = {"last_tick": None, "last_topup": None, "last_sweep_fire": None,
                 "last_export": None, "notes": []}


def _note(msg: str) -> None:
    print(f"[bt-scheduler] {msg}", flush=True)
    _status["notes"] = ([f"{datetime.now(LOCAL_TZ).isoformat(timespec='seconds')} {msg}"]
                        + _status["notes"])[:20]


def _artifact_file() -> str:
    return os.path.join(ARTIFACTS_PATH, "bt", "latest_sweep.json")


def _read_artifact() -> dict | None:
    try:
        with open(_artifact_file()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _bt_json(name: str) -> dict | None:
    try:
        with open(os.path.join(ARTIFACTS_PATH, "bt", name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_bt_json(name: str, content: dict) -> None:
    path = os.path.join(ARTIFACTS_PATH, "bt", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(content, f, indent=1, default=str)
    os.replace(tmp, path)


def _pending_proposals() -> list[dict]:
    """Evaluator-fed experiment queue (artifacts/bt/proposals.json, written by
    the LIVE evaluator over the same one-way-per-file bridge)."""
    entries = (_bt_json("proposals.json") or {}).get("proposals") or []
    return [e for e in entries
            if e.get("status") == "pending" and e.get("config_field")]


def _mark_proposals(from_status: str, to_status: str, sweep_id: str,
                    *, only_pending_ids: set[str] | None = None) -> None:
    """Move queue entries between lifecycle states, atomically rewriting the
    file. pending→testing stamps the sweep_id at fire time; testing→tested
    fires when that sweep's leaderboard exports; pending→invalid records an
    engine-rejected proposal (stale against the current active config) so the
    queue never shows it as tested-with-no-results. The flock serializes this
    read-modify-write against the evaluator's harvest (audit F1)."""
    from stock_strategy_shared.filelock import file_lock
    with file_lock(os.path.join(ARTIFACTS_PATH, "bt", "proposals.json.lock")):
        content = _bt_json("proposals.json") or {"proposals": []}
        changed = False
        for e in content.get("proposals") or []:
            if e.get("status") != from_status:
                continue
            if only_pending_ids is not None and e.get("id") not in only_pending_ids:
                continue
            if from_status == "testing" and e.get("sweep_id") != sweep_id:
                continue
            e["status"] = to_status
            if to_status == "testing":
                e["sweep_id"] = sweep_id
            changed = True
        if changed:
            _write_bt_json("proposals.json", content)


def _pending_full_experiments() -> list[dict]:
    """Evaluator-authored FULL-CONFIG candidates (kind='full_config') waiting
    in the same proposals.json queue the single-field diffs use."""
    entries = (_bt_json("proposals.json") or {}).get("proposals") or []
    return [e for e in entries
            if e.get("status") == "pending" and e.get("kind") == "full_config"
            and isinstance(e.get("config"), dict)]


def _mark_full_proposal(pid: str | None, to_status: str) -> None:
    if not pid:
        return
    from stock_strategy_shared.filelock import file_lock
    with file_lock(os.path.join(ARTIFACTS_PATH, "bt", "proposals.json.lock")):
        content = _bt_json("proposals.json") or {"proposals": []}
        for e in content.get("proposals") or []:
            if e.get("id") == pid:
                e["status"] = to_status
        _write_bt_json("proposals.json", content)


def _engine_window_keys(w: dict) -> dict:
    """lane vocabulary (period_a/period_b) -> bt-engine request vocabulary.

    The engine's schema predates the rename and is its own API; translating in
    one place is cheaper and safer than renaming across a service boundary that
    has already produced one dead-loop bug from a key mismatch."""
    return {"tune_start": w["period_a_start"], "tune_end": w["period_a_end"],
            "validate_start": w["period_b_start"], "validate_end": w["period_b_end"]}


async def _experiment_lane(client: httpx.AsyncClient, now: datetime,
                           cov: dict | None) -> None:
    """Phase 6c/6d: the wind tunnel's ONE driver — everything it runs is either
    the promotion yardstick or something the evaluator asked for.

    Each experiment is a single-config SWEEP job, which scores it over a TUNE
    window and a held-out VALIDATE window in one pass (reusing the tested
    run_config_both_windows path). That hold-out is what stops the loop from
    auto-promoting a config selected on the very data it was fitted to.

    Fires one at a time, capped per ISO week; experiments.json is both durable
    state and the results bridge the evaluator packet reads."""
    state = _bt_json("experiments.json") or {"experiments": []}
    exps = state["experiments"]
    changed = False

    # 1. Poll the in-flight experiment.
    for e in exps:
        if e.get("status") != "running" or not e.get("sweep_id"):
            continue
        try:
            sw = (await client.get(f"{BT_ENGINE_URL}/sweeps/latest")).json().get("sweep") or {}
            if sw.get("sweep_id") != e["sweep_id"]:
                continue
            if sw.get("status") not in ("success", "failed"):
                continue
            row = {}
            if sw.get("status") == "success":
                lb = (await client.get(
                    f"{BT_ENGINE_URL}/sweeps/{e['sweep_id']}/leaderboard",
                    params={"limit": 1})).json().get("leaderboard") or []
                row = lb[0] if lb else {}
        except Exception as exc:  # noqa: BLE001
            _note(f"experiment poll failed: {repr(exc)[:160]}")
            continue

        e["status"] = sw.get("status")
        e["completed_at"] = now.isoformat(timespec="seconds")
        e["result"] = {"period_a": row.get("in_sample"),
                       "period_b": row.get("out_sample"),
                       "error_message": row.get("error_message") or sw.get("error_message")}
        changed = True
        _mark_full_proposal(e.get("proposal_id"),
                            "tested" if sw.get("status") == "success" else "failed")
        _note(f"experiment {str(e.get('id'))[:8]} {e['status']} "
              f"(period_a CAGR={(row.get('in_sample') or {}).get('annualized_return')}, "
              f"period_b CAGR={(row.get('out_sample') or {}).get('annualized_return')})")

        # 2. Deterministic auto-promotion (paper mode). Baseline never promotes,
        # and NEITHER DOES A STRESS-REGIME RUN: its windows are a fixed historical
        # crisis, not the rolling tune/hold-out the gate is defined against, and
        # its two spans are crash/recovery halves rather than a hold-out pair.
        # Regime results are diagnostic — they feed findings and the ledger.
        if e.get("regime"):
            e["promotion"] = {"eligible": False,
                              "reason": f"stress regime {e['regime']} — diagnostic "
                                        "only, never promotable"}
            changed = True
        elif e["status"] == "success" and e.get("kind") == "full_config":
            base_entry = next((b for b in reversed(exps)
                               if b.get("kind") == "baseline"
                               and b.get("status") == "success"), None)
            base = (base_entry or {}).get("result")
            if (base_entry or {}).get("windows") != e.get("windows"):
                ok, why = False, "window mismatch vs baseline — not comparable"
            else:
                ok, why = promotion_eligible_2w(
                    e["result"], base, PROMOTE_MARGIN, PROMOTE_DD_TOLERANCE,
                    PROMOTE_VALIDATE_TOL, PROMOTE_TAIL_TOLERANCE)
            e["promotion"] = {"eligible": ok, "reason": why}
            # Score the evaluator's own committed prediction against ground
            # truth, on the SAME windows the gate used. Independent of whether
            # it promoted — a refused candidate is still a scored forecast.
            pred = score_prediction(e.get("predicted_tune_cagr_edge"),
                                    e.get("result"), base)
            if pred:
                e["prediction"] = pred
                _note(f"prediction {str(e.get('id'))[:8]}: predicted "
                      f"{pred['predicted_edge']:+.4f} actual {pred['actual_edge']:+.4f} "
                      f"(error {pred['error']:+.4f})")
            if ok and e.get("config") and e.get("config_hash"):
                _write_bt_json("promotion.json", {
                    "config": e["config"], "config_hash": e["config_hash"],
                    "candidate_id": e.get("id"), "hypothesis": e.get("hypothesis"),
                    "diff_vs_active": e.get("diff_vs_active"),
                    "evidence": {"candidate": e["result"], "baseline": base,
                                 "gate": why, "windows": e.get("windows")},
                    "promoted_at": now.isoformat(timespec="seconds"),
                })
                _note(f"PROMOTION: {str(e.get('id'))[:8]} passed the two-window "
                      f"gate ({why})")
            else:
                _note(f"no promotion for {str(e.get('id'))[:8]}: {why}")

    running = any(x.get("status") == "running" for x in exps)

    # 3. Fire the next experiment when the daily slot is open.
    if (not running and experiment_due(now, EXPERIMENT_HOUR)
            and cov and cov.get("go")
            and fired_this_week(exps, now.date()) < EXPERIMENTS_PER_WEEK):
        evs = date_fromiso(cov.get("earliest_viable_start"))
        windows = experiment_windows(now.date(), EXPERIMENT_RECENT_YEARS,
                                     EXPERIMENT_VALIDATE_MONTHS, evs)
        if windows is None:
            _note("experiment slot: derived period A too short — skipped")
            return

        applied_promo = None
        ps = _read_promotion_state() or {}
        if ps.get("status") == "applied":
            applied_promo = ps.get("last_hash")
        live_baseline = next((b for b in reversed(exps)
                              if b.get("kind") == "baseline"
                              and b.get("status") in ("running", "success")), None)
        base_ok, base_why = baseline_is_valid(live_baseline, applied_promo,
                                              today=now.date(),
                                              max_age_days=BASELINE_MAX_AGE_DAYS)
        if live_baseline is not None and live_baseline.get("status") == "running":
            base_ok = True

        entry = None
        import uuid as _uuid
        if base_ok and live_baseline and live_baseline.get("windows"):
            # PIN the candidate to the yardstick's windows. experiment_windows
            # is derived from `today`, so a candidate fired the day after the
            # baseline got a DIFFERENT window — and the gate's own
            # window-equality precondition ("window mismatch vs baseline — not
            # comparable") then refused every promotion. One experiment fires
            # per day, so the windows never matched and auto-promotion was
            # structurally unreachable. baseline_is_valid retires the yardstick
            # once its window ages past BASELINE_MAX_AGE_DAYS.
            windows = live_baseline["windows"]
        # THE ONE TRANSLATION. The lane speaks period_a/period_b (honest: nothing
        # is tuned, and for a stress regime the spans are crash/recovery halves);
        # bt-engine's request schema speaks tune_*/validate_*. Mapping here keeps
        # the engine API untouched and the misleading vocabulary out of
        # everything a human or the evaluator reads.
        payload = {"grid": {}, "max_configs": 1,
                   "rebalance_every": EXPERIMENT_REBALANCE_EVERY,
                   **_engine_window_keys(windows)}
        if not base_ok:
            # (Re-)run the yardstick FIRST: candidates must be gated against the
            # config that is actually live, over the SAME windows.
            entry = {"id": str(_uuid.uuid4()), "kind": "baseline",
                     "hypothesis": (f"BASELINE: active config, period A+B "
                                    f"({base_why})"),
                     "diff_vs_active": {}, "proposal_id": None,
                     "windows": windows, "applied_promotion": applied_promo}
        else:
            pend_full = _pending_full_experiments()
            if pend_full:
                # A COMPLETE candidate config is the only currency: to change one
                # field the evaluator sends the whole YAML with that field
                # changed, so what is tested is exactly what may go live.
                p = pend_full[0]
                payload["config"] = p["config"]
                cand_windows, regime = windows, p.get("regime")
                if regime:
                    # Fixed historical crisis instead of the rolling window. A
                    # refused regime (unknown name, or starting inside the factor
                    # warm-up runway) must not silently fall back to the rolling
                    # window — that would label a normal run as a stress test.
                    rw, why = regime_windows(regime, evs)
                    if rw is None:
                        _note(f"regime {regime} refused: {why}")
                        _mark_full_proposal(p.get("id"), "invalid")
                        return
                    cand_windows = rw
                    payload.update(_engine_window_keys(rw))
                entry = {"id": p.get("id"), "kind": "full_config",
                         "hypothesis": p.get("hypothesis"),
                         "diff_vs_active": p.get("diff"), "regime": regime,
                         "config": p.get("config"), "config_hash": p.get("config_hash"),
                         "predicted_tune_cagr_edge": p.get("predicted_tune_cagr_edge"),
                         "windows": cand_windows, "proposal_id": p.get("id")}
        if entry is None:
            return
        try:
            r = await client.post(f"{BT_ENGINE_URL}/sweeps/run", json=payload)
            if r.status_code == 200:
                entry.update({"sweep_id": r.json().get("sweep_id"),
                              "status": "running",
                              "fired_at": now.isoformat(timespec="seconds")})
                exps.append(entry)
                changed = True
                _mark_full_proposal(entry.get("proposal_id"), "testing")
                _note(f"experiment fired ({entry['kind']}) sweep "
                      f"{str(entry['sweep_id'])[:8]} A {windows['period_a_start']}"
                      f"→{windows['period_a_end']} B {windows['period_b_start']}"
                      f"→{windows['period_b_end']}")
            else:
                # 300, not 120: a coverage refusal names the offending FACTOR near
                # the end of the message, and a truncated "refused → 422" tells
                # an operator nothing actionable.
                _note(f"experiment fire refused → {r.status_code} {r.text[:300]}")
        except Exception as exc:  # noqa: BLE001
            _note(f"experiment fire failed: {repr(exc)[:160]}")

    if changed:
        state["experiments"] = exps[-60:]
        state["updated_at"] = now.isoformat(timespec="seconds")
        _write_bt_json("experiments.json", state)


# ── Last-known-good (root-cause fix for the flaky Lab) ────────────────────────
# The Lab's freshness was 100% coupled to a tick's HTTP polls ALL succeeding: a
# single coverage ReadTimeout / DNS blip during a container recreate blanked
# coverage to None and the UI flipped to "NO-GO (backfill needed)" even with 35M
# rows loaded. We persist the last SUCCESSFUL coverage/sweep and always serve it
# (stamped with its age) so a transient failure degrades to "data as of Nm ago".
_LAST_GOOD_FILE = "last_good.json"
_last_good: dict = {}


def _load_last_good() -> None:
    global _last_good
    _last_good = _bt_json(_LAST_GOOD_FILE) or {}


def _remember_good(key: str, value, now_iso: str) -> None:
    _last_good[key] = value
    _last_good[f"{key}_as_of"] = now_iso
    _write_bt_json(_LAST_GOOD_FILE, _last_good)


def _read_promotion_state() -> dict | None:
    """The live api's applied-promotion record (shared ./artifacts mount).
    Tells the lane whether the champion changed since its baseline ran."""
    try:
        with open(os.path.join(ARTIFACTS_PATH, "config",
                               "promotion_state.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def date_fromiso(v):
    """Lenient ISO-date parse (None-safe) for coverage-provided dates."""
    from datetime import date as _date
    try:
        return _date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _next_experiment_fire(now: datetime) -> str:
    """Human 'when does the lane next fire' — daily at EXPERIMENT_HOUR local."""
    fire = now.replace(hour=EXPERIMENT_HOUR, minute=0, second=0, microsecond=0)
    if now >= fire:
        fire = fire + timedelta(days=1)
    return fire.isoformat(timespec="minutes")


async def _experiment_snapshot(client: httpx.AsyncClient, now: datetime) -> dict:
    """Live experiment-lane view for the Lab: what is running (with progress and
    thesis), what is scheduled next and why, recent results, and the promotion
    outcome."""
    exps = (_bt_json("experiments.json") or {}).get("experiments") or []
    running = next((e for e in reversed(exps) if e.get("status") == "running"), None)
    progress, live = None, None
    # Ask the ENGINE what it is doing, ALWAYS — not only when the lane already
    # believes something of its own is running. A sweep started any other way
    # (a manual POST, a leftover from a previous scheduler) left the Lab
    # reporting "none running" while bt-engine sat pegged at 84% CPU. That is
    # the same blind spot that let three aborted nightly runs go unnoticed for
    # four weeks: the strip only ever described the lane's OWN bookkeeping,
    # never the machine.
    sw: dict = {}
    try:
        sw = (await client.get(f"{BT_ENGINE_URL}/sweeps/latest")).json().get("sweep") or {}
    except Exception:  # noqa: BLE001 — telemetry is best-effort
        sw = {}
    engine_busy = None
    if sw.get("status") == "running" and sw.get("sweep_id") != (running or {}).get("sweep_id"):
        _live = sw.get("live_stats")
        if isinstance(_live, str):
            try:
                _live = json.loads(_live)
            except ValueError:
                _live = None
        # Same telemetry the lane's own runs get — a foreign sweep is still a
        # multi-hour job, and a bare "busy" with no progress is why a stuck run
        # is indistinguishable from a working one.
        engine_busy = {"sweep_id": sw.get("sweep_id"),
                       "n_configs": sw.get("n_configs"), "n_done": sw.get("n_done"),
                       "progress_pct": sw.get("progress_pct"),
                       "started_at": sw.get("started_at"),
                       "live": _live, "owned_by_lane": False}
    if running and running.get("sweep_id"):
        try:
            if sw.get("sweep_id") == running["sweep_id"]:
                # progress_pct is per-SESSION within the config (n_done only
                # moves 0->1 for a single-config experiment — no granularity).
                progress = sw.get("progress_pct")
                live = sw.get("live_stats")
                if isinstance(live, str):
                    live = json.loads(live)
        except Exception:  # noqa: BLE001 — telemetry is best-effort
            progress, live = None, None
    props = (_bt_json("proposals.json") or {}).get("proposals") or []
    queued = [{"kind": e.get("kind", "single_field"),
               "hypothesis": e.get("hypothesis")
               or (f"{e.get('config_field')} → {e.get('value')}"
                   if e.get("config_field") else "—")}
              for e in props if e.get("status") == "pending"]
    if not any(e.get("kind") == "baseline" and e.get("status") in ("running", "success")
               for e in exps):
        queued.insert(0, {"kind": "baseline",
                          "hypothesis": "BASELINE: active config (promotion yardstick)"})
    # The FULL per-window summaries ride along so the Lab UI can expand a run
    # into CAGR / drawdown / SPY / turnover / terminal wealth. Previously only
    # `cagr` was projected, so everything the simulator computed was reachable
    # solely by querying bt-postgres by hand. Five entries, two summaries each —
    # bounded, and this artifact is read by a browser, not pasted into a prompt.
    recent = [{"kind": e.get("kind"), "status": e.get("status"),
               "hypothesis": e.get("hypothesis"),
               "cagr": ((e.get("result") or {}).get("period_b") or {}).get("annualized_return"),
               "promotion": (e.get("promotion") or {}).get("reason"),
               "completed_at": e.get("completed_at"),
               "windows": e.get("windows"),
               "regime": e.get("regime"),
               "config_hash": e.get("config_hash"),
               "result": e.get("result")}
              for e in exps if e.get("status") in ("success", "failed")][-5:]
    # The cap counts CANDIDATES only (a baseline tests no hypothesis). Report
    # baseline fires separately rather than hiding them — "0/5 fired" next to a
    # busy lane would look broken.
    n_fired = fired_this_week(exps, now.date())
    n_baseline = fired_this_week(exps, now.date(), kinds=("baseline",))
    next_fire = _next_experiment_fire(now)
    promo = _bt_json("promotion.json")
    return {
        "running": ({"kind": running.get("kind"),
                     "hypothesis": running.get("hypothesis"),
                     "fired_at": running.get("fired_at"),
                     "windows": running.get("windows"),
                     "progress_pct": progress,
                     "live": live} if running else None),
        "queued": queued[:8],
        "schedule": build_schedule(queued, next_fire, n_fired, EXPERIMENTS_PER_WEEK),
        "recent": recent,
        "engine_busy": engine_busy,
        "next_fire_local": next_fire,
        "fired_this_week": n_fired,
        "baselines_this_week": n_baseline,
        "week_cap": EXPERIMENTS_PER_WEEK,
        "window_years": EXPERIMENT_RECENT_YEARS,
        "validate_months": EXPERIMENT_VALIDATE_MONTHS,
        "last_promotion": ({"config_hash": promo.get("config_hash"),
                            "promoted_at": promo.get("promoted_at"),
                            "hypothesis": promo.get("hypothesis"),
                            "gate": (promo.get("evidence") or {}).get("gate")}
                           if promo else None),
        "promotion_applied": _read_promotion_state(),
    }


def _write_status_artifact(snapshot: dict) -> None:
    """artifacts/bt/status.json — the read-only Lab tab's data source (same
    one-way file bridge as the sweep leaderboard; works co-located and across
    machines)."""
    try:
        path = os.path.join(ARTIFACTS_PATH, "bt", "status.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snapshot, f, indent=1, default=str)
        os.replace(tmp, path)
    except OSError as exc:
        _note(f"status artifact write failed: {exc}")


async def _tick() -> None:
    now = datetime.now(LOCAL_TZ)
    _status["last_tick"] = now.isoformat(timespec="seconds")
    snapshot: dict = {"generated_at": now.isoformat(timespec="seconds"),
                      "scheduler": None, "data_runs": None, "coverage": None,
                      "sweep_latest": None}
    async with httpx.AsyncClient(timeout=30.0) as client:
        # ── daily topup ───────────────────────────────────────────────────────
        try:
            runs = (await client.get(f"{BT_DATA_URL}/runs/latest")).json().get("runs", [])
            snapshot["data_runs"] = runs[:3]
            running = any(r.get("status") == "running" for r in runs)
            last_ok = next((r for r in runs if r.get("status") == "success"), None)
            last_date = (datetime.fromisoformat(
                str(last_ok["started_at"]).replace("Z", "+00:00")).date()
                if last_ok and last_ok.get("started_at") else None)
            # topup_due dedupes on bt-data's own success rows; a REFUSED topup
            # (404/409, e.g. empty DB pre-backfill) never writes one, so without
            # this in-memory guard every tick from TOPUP_HOUR to midnight would
            # re-POST. One attempt per local day is enough — upserts are
            # idempotent, so the once-per-restart re-fire is harmless.
            fired_today = (_status["last_topup"] is not None and
                           datetime.fromisoformat(_status["last_topup"]).date() == now.date())
            if not running and not fired_today and topup_due(now, last_date, hour=TOPUP_HOUR):
                r = await client.post(f"{BT_DATA_URL}/jobs/topup")
                _status["last_topup"] = now.isoformat(timespec="seconds")
                _note(f"topup fired → {r.status_code} {r.text[:120]}")
        except Exception as exc:  # noqa: BLE001
            _note(f"topup check failed: {exc}")

        # ── coverage snapshot (Lab tab + sweep gate) ─────────────────────────
        # Longer, coverage-specific timeout: even the fast stats path can be a
        # few seconds on a loaded NAS, and a slow answer must not be treated as
        # "no data". On ANY failure we fall back to last-known-good (below), so
        # the Lab shows real coverage stamped with its age, never blank.
        cov = None
        try:
            cov = (await client.get(f"{BT_DATA_URL}/data/coverage",
                                    timeout=60.0)).json()
            snapshot["coverage"] = cov
            _remember_good("coverage", cov, now.isoformat(timespec="seconds"))
        except Exception as exc:  # noqa: BLE001
            _note(f"coverage check failed (serving last-good): {repr(exc)[:160]}")
        # ALWAYS surface last-known-good coverage + its age, so a transient poll
        # failure degrades to "as of Nm ago", not "NO-GO (backfill needed)".
        if snapshot.get("coverage") is None and _last_good.get("coverage") is not None:
            snapshot["coverage"] = _last_good["coverage"]
            snapshot["coverage_stale"] = True
        snapshot["coverage_as_of"] = _last_good.get("coverage_as_of")

        # ── Phase 6c: daily full-config experiment lane (+ auto-baseline) ─────
        # Use the EFFECTIVE coverage (live poll OR last-known-good) so a
        # transient coverage blip on the firing tick can't silently skip the
        # baseline/experiment — same root-cause decoupling as the display.
        try:
            await _experiment_lane(client, now, snapshot.get("coverage"))
        except Exception as exc:  # noqa: BLE001
            _note(f"experiment lane failed: {exc}")

        # ── weekly standing GRID (legacy Phase 5 — RETIRED by default) ────────
        # The hand-written 54-config grid predates evaluator-authored
        # configs: it is not driven by the evaluator, it carried the
        # universe_limit look-ahead bias, and it competed with the lane for
        # the engine. The lane now runs everything (baseline, full-config
        # candidates, AND single-field proposals) with a validation window.
        try:
            if STANDING_SWEEP_ENABLED and os.path.exists(SPEC_PATH):
                latest = (await client.get(f"{BT_ENGINE_URL}/sweeps/latest")).json().get("sweep")
                if sweep_due(now, latest, weekday=SWEEP_WEEKDAY, hour=SWEEP_HOUR):
                    with open(SPEC_PATH, "rb") as f:
                        spec_bytes = f.read()
                    spec_hash = hashlib.sha256(spec_bytes).hexdigest()[:16]
                    pending = _pending_proposals()
                    needed, why = sweep_needed(
                        spec_hash, _bt_json("sweep_state.json"), len(pending),
                        now.date(), force_refresh_days=FORCE_REFRESH_DAYS)
                    if not needed:
                        # skipping creates no sweep row, so due-ness persists all
                        # evening — note once per day, not per tick
                        if _status.get("last_skip_note", "")[:10] != now.date().isoformat():
                            _status["last_skip_note"] = now.isoformat(timespec="seconds")
                            _note(f"sweep due but skipped: {why}")
                    elif not cov or not cov.get("go"):
                        if _status.get("last_nogo_note", "")[:10] != now.date().isoformat():
                            _status["last_nogo_note"] = now.isoformat(timespec="seconds")
                            _note("sweep due but coverage NO-GO — skipped (backfill first)")
                    else:
                        spec = json.loads(spec_bytes)
                        evs = cov.get("earliest_viable_start")
                        windows = derive_windows(
                            spec, now.date(),
                            datetime.fromisoformat(evs).date() if evs else None)
                        if windows is None:
                            _note("sweep due but derived tune window too short — skipped")
                        else:
                            payload = {"grid": spec.get("grid", {}), **windows,
                                       **(spec.get("params") or {}),
                                       "extra_configs": [
                                           {p["config_field"]: p.get("value")}
                                           for p in pending]}
                            r = await client.post(f"{BT_ENGINE_URL}/sweeps/run", json=payload)
                            _status["last_sweep_fire"] = now.isoformat(timespec="seconds")
                            _note(f"standing sweep fired ({why}) → "
                                  f"{r.status_code} {r.text[:300]}")
                            if r.status_code == 200:
                                rbody = r.json()
                                sid = rbody.get("sweep_id", "")
                                _write_bt_json("sweep_state.json", {
                                    "last_spec_hash": spec_hash,
                                    "last_fired_at": now.isoformat(timespec="seconds"),
                                    "last_sweep_id": sid,
                                    "reason": why,
                                })
                                if pending:
                                    # Audit F2: the engine reports which extras it
                                    # DROPPED (stale/invalid vs the current active
                                    # config, e.g. after a one-click apply mid-week).
                                    # Only accepted proposals go 'testing'; dropped
                                    # ones go 'invalid' — never tested-with-no-rows.
                                    dropped = rbody.get("extra_dropped_diffs") or []
                                    accepted = {p["id"] for p in pending
                                                if {p["config_field"]: p.get("value")}
                                                not in dropped}
                                    rejected = {p["id"] for p in pending} - accepted
                                    if accepted:
                                        _mark_proposals("pending", "testing", sid,
                                                        only_pending_ids=accepted)
                                    if rejected:
                                        _mark_proposals("pending", "invalid", sid,
                                                        only_pending_ids=rejected)
                                    _note(f"{len(accepted)} proposal(s) riding sweep "
                                          f"{sid[:8]}"
                                          + (f", {len(rejected)} invalid (stale vs "
                                             f"active config)" if rejected else ""))
        except Exception as exc:  # noqa: BLE001
            _note(f"sweep check failed: {exc}")

        # ── results bridge export ─────────────────────────────────────────────
        try:
            latest = (await client.get(f"{BT_ENGINE_URL}/sweeps/latest")).json().get("sweep")
            snapshot["sweep_latest"] = latest
            if latest:
                _remember_good("sweep_latest", latest, now.isoformat(timespec="seconds"))
            # The LANE also creates sweeps (one config, tune+validate). Those are
            # NOT grid results and must not be exported as latest_sweep.json —
            # the packet renders that as backtest_lab "decision-grade walk-forward
            # sweep leaderboard", so exporting a 1-row experiment there would
            # both mislabel it and duplicate the experiment_lane section.
            lane_sweep_ids = {e.get("sweep_id") for e in
                              ((_bt_json("experiments.json") or {}).get("experiments") or [])
                              if e.get("sweep_id")}
            if latest and latest.get("sweep_id") in lane_sweep_ids:
                pass
            elif artifact_needed(latest, _read_artifact()):
                lb = (await client.get(
                    f"{BT_ENGINE_URL}/sweeps/{latest['sweep_id']}/leaderboard",
                    params={"limit": 25})).json().get("leaderboard", [])
                # Tag rows that came from the evaluator's experiment queue so the
                # next review recognizes its own past proposals in the results.
                proposal_diffs = [
                    {e["config_field"]: e.get("value")}
                    for e in (_bt_json("proposals.json") or {}).get("proposals") or []
                    if e.get("sweep_id") == latest["sweep_id"]]
                for row in lb:
                    if row.get("config_diff") in proposal_diffs:
                        row["proposal"] = True
                artifact = {
                    "generated_at": now.isoformat(timespec="seconds"),
                    "sweep_id": latest["sweep_id"],
                    "status": latest["status"],
                    "n_configs": latest.get("n_configs"),
                    "windows": {k: latest.get(k) for k in
                                ("tune_start", "tune_end", "validate_start", "validate_end")},
                    "leaderboard": lb,
                    "note": ("walk-forward sweep from the isolated deep-history "
                             "backtester; rank by oos_sharpe, large overfit_gap = "
                             "fit the tune window, not the market"),
                }
                path = _artifact_file()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(artifact, f, indent=1, default=str)
                os.replace(tmp, path)
                _status["last_export"] = now.isoformat(timespec="seconds")
                _mark_proposals("testing", "tested", latest["sweep_id"])
                _note(f"exported leaderboard for sweep {latest['sweep_id']}")
        except Exception as exc:  # noqa: BLE001
            _note(f"export check failed: {exc}")

        # ── experiment-lane view (progress + queued theses + next fire) ───────
        try:
            snapshot["experiments"] = await _experiment_snapshot(client, now)
        except Exception as exc:  # noqa: BLE001
            _note(f"experiment snapshot failed: {repr(exc)[:160]}")

    # sweep_latest last-good fallback (same rationale as coverage)
    if snapshot.get("sweep_latest") is None and _last_good.get("sweep_latest") is not None:
        snapshot["sweep_latest"] = _last_good["sweep_latest"]
        snapshot["sweep_stale"] = True
    snapshot["scheduler"] = dict(_status)
    _write_status_artifact(snapshot)


async def _loop() -> None:
    while True:
        try:
            await _tick()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(TICK_SECS)


@asynccontextmanager
async def lifespan(application: FastAPI):
    _load_last_good()   # serve real coverage immediately, before the first tick
    task = asyncio.create_task(_loop())
    yield
    task.cancel()


app = FastAPI(title="bt-scheduler", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "bt-scheduler"}


@app.get("/status")
async def status():
    return _status
