"""
stale_guards — verifies risk-service MAX_DATA_AGE_HOURS and MAX_SYNC_AGE_HOURS.

Two safety guards in risk-service are never triggered by normal harness runs
because the harness always runs fresh pipeline + sync before submitting trades.

This scenario intentionally makes pipeline_runs and alpaca_sync_runs stale
by updating their completed_at timestamps, then tries to submit trade intents.
It expects risk_rejected in both cases, then restores freshness and expects
the trades to succeed.

Guard thresholds (risk-service defaults):
  MAX_DATA_AGE_HOURS = 96   → we make pipeline 200h stale
  MAX_SYNC_AGE_HOURS = 24   → we make sync 30h stale
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any, List

import aiohttp

from tests.harness.harness.driver import _get_pending_intents_from_db
from tests.harness.harness.scenario import RegimeChange, Scenario

if TYPE_CHECKING:
    from tests.harness.harness.driver import SimulationDriver

log = logging.getLogger("harness.stale_guards")


class _StaleGuardHook:
    """Fires once — on the first day that produces ≥ 2 entry intents."""

    def __init__(self) -> None:
        self._fired = False

    async def __call__(
        self,
        driver: "SimulationDriver",
        session: aiohttp.ClientSession,
        errors: List[str],
    ) -> None:
        if self._fired or not driver._current_delta_run_id:
            return

        intents = await _get_pending_intents_from_db(driver.dsn, driver._current_delta_run_id)
        entry_intents = [i for i in intents if i.get("action") == "entry"]
        if len(entry_intents) < 2:
            log.info("[stale_guards] only %d entry intents today — waiting for next day", len(entry_intents))
            return

        self._fired = True
        day = driver._current_trading_day.isoformat() if driver._current_trading_day else "?"
        log.info("[stale_guards] firing on day %s (%d entry intents)", day, len(entry_intents))

        i0 = entry_intents[0]
        i1 = entry_intents[1]

        # ── Test 1: stale pipeline → MAX_DATA_AGE_HOURS (default 96h) ──
        log.info("[stale_guards] Test 1: pipeline stale by 200h (threshold=96h)")
        await driver._make_pipeline_stale(hours=200.0)
        r0 = await driver._submit_single_intent(session, i0["id"])
        if r0.get("status") != "risk_rejected":
            errors.append(
                f"stale_guards[data_age]: expected risk_rejected, got '{r0.get('status')}' "
                f"(response={r0})"
            )
        else:
            log.info("[stale_guards] Test 1 PASS: risk_rejected as expected")

        # Restore freshness and resubmit — should succeed this time.
        await driver._restore_pipeline_freshness()
        r0b = await driver._submit_single_intent(session, i0["id"])
        if r0b.get("status") not in ("submitted", "deferred", "pending", "filled"):
            errors.append(
                f"stale_guards[data_age_restore]: expected submitted/deferred, "
                f"got '{r0b.get('status')}' (response={r0b})"
            )
        else:
            log.info("[stale_guards] Test 1 restore PASS: %s", r0b.get("status"))

        # ── Test 2: stale alpaca-sync → MAX_SYNC_AGE_HOURS (default 24h) ──
        # trade-executor catches stale sync during sizing (before risk-service) and raises
        # HTTPException(409) → {"detail": "..."}. Risk-service has its own MAX_SYNC_AGE_HOURS
        # guard too. Either format counts as a valid stale-sync rejection.
        log.info("[stale_guards] Test 2: alpaca-sync stale by 30h (threshold=24h)")
        await driver._make_sync_stale(hours=30.0)
        r1 = await driver._submit_single_intent(session, i1["id"])
        stale_sync_blocked = (
            r1.get("status") == "risk_rejected"
            or ("detail" in r1 and "alpaca-sync" in r1.get("detail", ""))
        )
        if not stale_sync_blocked:
            errors.append(
                f"stale_guards[sync_age]: expected risk_rejected, got '{r1.get('status')}' "
                f"(response={r1})"
            )
        else:
            log.info("[stale_guards] Test 2 PASS: stale sync blocked as expected")

        # Restore freshness and resubmit.
        await driver._restore_sync_freshness()
        r1b = await driver._submit_single_intent(session, i1["id"])
        if r1b.get("status") not in ("submitted", "deferred", "pending", "filled"):
            errors.append(
                f"stale_guards[sync_age_restore]: expected submitted/deferred, "
                f"got '{r1b.get('status')}' (response={r1b})"
            )
        else:
            log.info("[stale_guards] Test 2 restore PASS: %s", r1b.get("status"))

        # Submit all remaining intents normally so the simulation stays healthy.
        done_ids = {i0["id"], i1["id"]}
        for intent in intents:
            if intent["id"] in done_ids:
                continue
            if intent.get("action") not in ("entry", "exit", "buy_add", "sell_trim"):
                continue
            await driver._submit_single_intent(session, intent["id"])


_hook = _StaleGuardHook()

STALE_GUARDS = Scenario(
    name="stale_guards",
    description=(
        "6-day simulation. On the first day with ≥2 entry intents, the post_delta_hook "
        "deliberately makes pipeline_runs stale (200h > MAX_DATA_AGE_HOURS=96h) and "
        "alpaca_sync_runs stale (30h > MAX_SYNC_AGE_HOURS=24h), verifying risk_rejected "
        "in both cases. Freshness is restored and retried; the retry must succeed. "
        "skip_manual_approve=True because the hook handles all submission."
    ),
    seed=11,
    universe_size=60,
    start_date=date(2024, 1, 2),
    end_date=date(2024, 1, 9),  # 6 trading days — need ≥3 for confirmation_days to produce entries
    regimes=[
        RegimeChange(start_date=date(2024, 1, 2), regime_type="bull_calm"),
    ],
    run_vetter=False,
    skip_manual_approve=True,
    post_delta_hook=_hook,
)
