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
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

from app.logic import (artifact_needed, derive_windows, experiment_due,
                       fired_this_week, sweep_due, sweep_needed, topup_due)

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


async def _experiment_lane(client: httpx.AsyncClient, now: datetime,
                           cov: dict | None) -> None:
    """Phase 6c: poll the in-flight experiment; fire the next one when the
    daily slot opens. One at a time; weekly fire cap; auto-baseline first.
    experiments.json doubles as durable state and the results bridge the
    evaluator packet reads."""
    state = _bt_json("experiments.json") or {"experiments": []}
    exps = state["experiments"]
    changed = False

    # 1. Poll the running experiment (if any).
    for e in exps:
        if e.get("status") != "running" or not e.get("run_id"):
            continue
        try:
            r = (await client.get(f"{BT_ENGINE_URL}/runs/{e['run_id']}")
                 ).json().get("run") or {}
        except Exception as exc:  # noqa: BLE001
            _note(f"experiment poll failed: {exc}")
            continue
        if r.get("status") in ("success", "failed"):
            e["status"] = r["status"]
            e["completed_at"] = now.isoformat(timespec="seconds")
            e["result"] = {k: r.get(k) for k in (
                "total_return", "annualized_return", "sharpe_ratio",
                "max_drawdown", "benchmark_total_return", "alpha",
                "start_date", "end_date", "error_message")}
            changed = True
            _mark_full_proposal(e.get("proposal_id"),
                                "tested" if r["status"] == "success" else "failed")
            _note(f"experiment {e.get('id', '?')[:8]} {r['status']} "
                  f"(CAGR={r.get('annualized_return')})")

    running = any(e.get("status") == "running" for e in exps)

    # 2. Fire the next one when the slot is open.
    if (not running and experiment_due(now, EXPERIMENT_HOUR)
            and cov and cov.get("go")
            and fired_this_week(exps, now.date()) < EXPERIMENTS_PER_WEEK):
        try:
            sweep = (await client.get(f"{BT_ENGINE_URL}/sweeps/latest")
                     ).json().get("sweep")
        except Exception:  # noqa: BLE001
            sweep = None
        if sweep and sweep.get("status") == "running":
            pass  # never contend with a sweep for the engine/host
        else:
            evs = cov.get("earliest_viable_start")
            payload = {"start_date": evs, "end_date": now.date().isoformat(),
                       "rebalance_every": EXPERIMENT_REBALANCE_EVERY}
            pending = _pending_full_experiments()
            entry = None
            if pending:
                p = pending[0]
                payload["config"] = p["config"]
                entry = {"id": p.get("id"), "kind": "full_config",
                         "hypothesis": p.get("hypothesis"),
                         "diff_vs_active": p.get("diff"),
                         "proposal_id": p.get("id")}
            elif not any(e.get("kind") == "baseline" for e in exps):
                # One-time auto-baseline: the ACTIVE config over full history —
                # the "switched on 20 years ago" anchor. bt-engine loads its
                # own STRATEGY_CONFIG_PATH when no config is passed. Caveat:
                # the active config was designed with hindsight → closer to
                # in-sample; rolling OOS remains the honest estimate.
                import uuid as _uuid
                entry = {"id": str(_uuid.uuid4()), "kind": "baseline",
                         "hypothesis": ("BASELINE: active config over full "
                                        "history (hindsight caveat applies)"),
                         "diff_vs_active": {}, "proposal_id": None}
            if entry:
                try:
                    r = await client.post(f"{BT_ENGINE_URL}/jobs/run", json=payload)
                    if r.status_code == 200:
                        entry.update({"run_id": r.json().get("run_id"),
                                      "status": "running",
                                      "fired_at": now.isoformat(timespec="seconds")})
                        exps.append(entry)
                        changed = True
                        _mark_full_proposal(entry.get("proposal_id"), "testing")
                        _note(f"experiment fired ({entry['kind']}) run "
                              f"{entry['run_id'][:8]}")
                    else:
                        _note(f"experiment fire refused → {r.status_code} "
                              f"{r.text[:120]}")
                except Exception as exc:  # noqa: BLE001
                    _note(f"experiment fire failed: {exc}")

    if changed:
        state["experiments"] = exps[-60:]   # bounded history
        state["updated_at"] = now.isoformat(timespec="seconds")
        _write_bt_json("experiments.json", state)


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
        cov = None
        try:
            cov = (await client.get(f"{BT_DATA_URL}/data/coverage")).json()
            snapshot["coverage"] = cov
        except Exception as exc:  # noqa: BLE001
            # repr, not str: httpx timeouts stringify to '' — the reasonless
            # "coverage check failed:" notes that made the Lab look haunted.
            _note(f"coverage check failed: {repr(exc)[:200]}")

        # ── Phase 6c: daily full-config experiment lane (+ auto-baseline) ─────
        try:
            await _experiment_lane(client, now, cov)
        except Exception as exc:  # noqa: BLE001
            _note(f"experiment lane failed: {exc}")

        # ── weekly standing sweep (skip-if-unchanged + experiment queue) ──────
        try:
            if os.path.exists(SPEC_PATH):
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
                                  f"{r.status_code} {r.text[:120]}")
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
            if artifact_needed(latest, _read_artifact()):
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
