"""Cross-service invariant: every service that computes "today" for chain
sequencing MUST agree on the calendar date.

WHY THIS EXISTS (the expensive lesson):
The scheduler decides "did step X run today?" by comparing its OWN notion of
today against a date another service wrote (pipeline.chain_date, etc.). For weeks
this looped — most recently because commit a00155e made the scheduler compute
`today` in explicit ET (SCHEDULE_TZ) while the pipeline still used the implicit
container TZ (UTC) for chain_date. In the evening-ET window the two disagreed by
one calendar day, the scheduler's done-check never matched, and it force-
re-triggered the pipeline every tick (infinite loop + vetter LLM credit burn).

Both services now derive "today" from the SAME explicit SCHEDULE_TZ, with
_local_today() helpers. This test pins that agreement so a FUTURE divergence —
a service reintroducing date.today(), a different default zone, a dropped env
var — fails in CI instead of at 20:40 on a Saturday in production.

We run each service in its OWN subprocess because the per-service test conftests
all bind the package name `app` to a different services/<x>/app, so they cannot
be imported together in one interpreter. Subprocesses also let us stub
apscheduler (not installed in the test env) and force TZ to reproduce the exact
UTC/ET split that caused the bug.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Each entry: service dir under services/, plus the names of the TZ symbols its
# app.main exposes. All chain-sequencing services must expose _local_today() and
# SCHEDULE_TZ_NAME; risk-service additionally has its own RISK_TZ for the daily
# loss baseline, which must also match.
_CHAIN_SERVICES = ["scheduler", "pipeline"]


def _probe(service: str, tz_env: str | None) -> dict:
    """Import services/<service>/app/main in a clean subprocess and report its
    SCHEDULE_TZ_NAME and _local_today(). tz_env forces the container TZ (or None
    to leave it unset) so we can reproduce the UTC/ET split."""
    code = textwrap.dedent(
        f"""
        import os, sys, json, types

        ROOT = {ROOT!r}
        sys.path.insert(0, os.path.join(ROOT, "shared"))
        sys.path.insert(0, os.path.join(ROOT, "services", {service!r}))

        # Import-time env the modules expect.
        os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@x/x")
        os.environ.setdefault("STRATEGY_CONFIG_PATH",
                              os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))

        # Stub apscheduler (scheduler imports it; not installed in test env).
        for name in ("apscheduler", "apscheduler.schedulers",
                     "apscheduler.schedulers.asyncio", "apscheduler.triggers",
                     "apscheduler.triggers.cron", "apscheduler.triggers.interval"):
            sys.modules.setdefault(name, types.ModuleType(name))
        class _M:
            def __getattr__(self, _): return _M()
            def __call__(self, *a, **k): return _M()
        sys.modules["apscheduler.schedulers.asyncio"].AsyncIOScheduler = _M()
        sys.modules["apscheduler.triggers.cron"].CronTrigger = _M()
        sys.modules["apscheduler.triggers.interval"].IntervalTrigger = _M()

        # Stub redis.asyncio (pipeline imports it).
        try:
            import redis.asyncio  # noqa
        except Exception:
            r = types.ModuleType("redis"); ra = types.ModuleType("redis.asyncio")
            re_ = types.ModuleType("redis.exceptions")
            class _TE(Exception): pass
            re_.TimeoutError = _TE
            ra.Redis = _M(); ra.from_url = lambda *a, **k: _M()
            r.asyncio = ra; r.exceptions = re_
            sys.modules["redis"] = r; sys.modules["redis.asyncio"] = ra
            sys.modules["redis.exceptions"] = re_

        import app.main as m
        out = {{
            "schedule_tz_name": getattr(m, "SCHEDULE_TZ_NAME", None),
            "local_today": m._local_today().isoformat(),
        }}
        print(json.dumps(out))
        """
    )
    env = dict(os.environ)
    env.pop("TZ", None)
    if tz_env is not None:
        env["TZ"] = tz_env
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=60,
    )
    assert proc.returncode == 0, (
        f"probe of {service} (TZ={tz_env}) failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    )
    # Last stdout line is our JSON (modules may print startup noise above it).
    line = [l for l in proc.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
    return json.loads(line)


@pytest.mark.parametrize("tz_env", [None, "UTC", "America/New_York", "America/Los_Angeles"])
def test_all_chain_services_agree_on_today(tz_env):
    """Every chain service must compute the SAME _local_today(), regardless of the
    container TZ env var — including TZ=UTC, the exact condition that produced the
    scheduler(ET=05-30) vs pipeline(UTC=05-31) split-brain loop."""
    results = {svc: _probe(svc, tz_env) for svc in _CHAIN_SERVICES}
    todays = {svc: r["local_today"] for svc, r in results.items()}
    assert len(set(todays.values())) == 1, (
        f"chain services disagree on today under TZ={tz_env}: {todays} — "
        "this is the re-trigger-loop bug class; all must derive 'today' from SCHEDULE_TZ"
    )


@pytest.mark.parametrize("tz_env", [None, "UTC"])
def test_all_chain_services_share_schedule_tz_name(tz_env):
    """They must also resolve the SAME SCHEDULE_TZ_NAME (one shared env var)."""
    names = {svc: _probe(svc, tz_env)["schedule_tz_name"] for svc in _CHAIN_SERVICES}
    assert len(set(names.values())) == 1, f"SCHEDULE_TZ_NAME differs across services: {names}"
    assert all(n == "America/New_York" for n in names.values()), names


def test_chain_services_today_is_eastern_not_utc_in_evening_window():
    """Sanity that the agreed 'today' actually follows ET: we can't freeze the clock
    across subprocesses, but we CAN assert that with TZ=UTC forced, the services
    still return the ET date (not the process/UTC date) — i.e. they don't silently
    fall back to the container zone."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        et_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        pytest.skip("zoneinfo unavailable")
    for svc in _CHAIN_SERVICES:
        got = _probe(svc, "UTC")["local_today"]
        assert got == et_today, (
            f"{svc} returned {got} under TZ=UTC but ET today is {et_today} — "
            "service is using the container TZ instead of SCHEDULE_TZ"
        )
