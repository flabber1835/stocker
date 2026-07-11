"""bt-scheduler — automation for the backtest stack (backtest machine only).

Tick loop (BT_SCHED_TICK_SECS): daily Sharadar topup, weekly standing sweep from
the versioned spec (sweeps/standing_sweep.json, relative windows), and the
results bridge — exporting the latest completed sweep's leaderboard to
artifacts/bt/latest_sweep.json, which the LIVE evaluator's packet reads
(co-located: shared ./artifacts mount; separate machines: any file transport).
The bridge is ONE-WAY files — no network path between the stacks, preserving the
isolation decision. Decision logic is pure (app/logic.py); this file is I/O.
"""
from __future__ import annotations

import asyncio
import json
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

from app.logic import artifact_needed, derive_windows, sweep_due, topup_due

BT_DATA_URL = os.getenv("BT_DATA_URL", "http://bt-data:8000")
BT_ENGINE_URL = os.getenv("BT_ENGINE_URL", "http://bt-engine:8000")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "/artifacts")
SPEC_PATH = os.getenv("STANDING_SWEEP_SPEC", "/sweeps/standing_sweep.json")
TICK_SECS = float(os.getenv("BT_SCHED_TICK_SECS", "300"))
TOPUP_HOUR = int(os.getenv("BT_TOPUP_HOUR", "23"))
SWEEP_WEEKDAY = int(os.getenv("BT_SWEEP_WEEKDAY", "5"))   # Mon=0 … Sat=5
SWEEP_HOUR = int(os.getenv("BT_SWEEP_HOUR", "2"))
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


async def _tick() -> None:
    now = datetime.now(LOCAL_TZ)
    _status["last_tick"] = now.isoformat(timespec="seconds")
    async with httpx.AsyncClient(timeout=30.0) as client:
        # ── daily topup ───────────────────────────────────────────────────────
        try:
            runs = (await client.get(f"{BT_DATA_URL}/runs/latest")).json().get("runs", [])
            running = any(r.get("status") == "running" for r in runs)
            last_ok = next((r for r in runs if r.get("status") == "success"), None)
            last_date = (datetime.fromisoformat(
                str(last_ok["started_at"]).replace("Z", "+00:00")).date()
                if last_ok and last_ok.get("started_at") else None)
            if not running and topup_due(now, last_date, hour=TOPUP_HOUR):
                r = await client.post(f"{BT_DATA_URL}/jobs/topup")
                _status["last_topup"] = now.isoformat(timespec="seconds")
                _note(f"topup fired → {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            _note(f"topup check failed: {exc}")

        # ── weekly standing sweep ─────────────────────────────────────────────
        try:
            if os.path.exists(SPEC_PATH):
                latest = (await client.get(f"{BT_ENGINE_URL}/sweeps/latest")).json().get("sweep")
                if sweep_due(now, latest, weekday=SWEEP_WEEKDAY, hour=SWEEP_HOUR):
                    cov = (await client.get(f"{BT_DATA_URL}/data/coverage")).json()
                    if not cov.get("go"):
                        _note("sweep due but coverage NO-GO — skipped (backfill first)")
                    else:
                        with open(SPEC_PATH) as f:
                            spec = json.load(f)
                        evs = cov.get("earliest_viable_start")
                        windows = derive_windows(
                            spec, now.date(),
                            datetime.fromisoformat(evs).date() if evs else None)
                        if windows is None:
                            _note("sweep due but derived tune window too short — skipped")
                        else:
                            payload = {"grid": spec.get("grid", {}), **windows,
                                       **(spec.get("params") or {})}
                            r = await client.post(f"{BT_ENGINE_URL}/sweeps/run", json=payload)
                            _status["last_sweep_fire"] = now.isoformat(timespec="seconds")
                            _note(f"standing sweep fired → {r.status_code} {r.text[:120]}")
        except Exception as exc:  # noqa: BLE001
            _note(f"sweep check failed: {exc}")

        # ── results bridge export ─────────────────────────────────────────────
        try:
            latest = (await client.get(f"{BT_ENGINE_URL}/sweeps/latest")).json().get("sweep")
            if artifact_needed(latest, _read_artifact()):
                lb = (await client.get(
                    f"{BT_ENGINE_URL}/sweeps/{latest['sweep_id']}/leaderboard",
                    params={"limit": 25})).json().get("leaderboard", [])
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
                _note(f"exported leaderboard for sweep {latest['sweep_id']}")
        except Exception as exc:  # noqa: BLE001
            _note(f"export check failed: {exc}")


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
