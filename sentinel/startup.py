"""Drives the ownership state machine against a real broker.

The loop is deliberately dull: observe, plan, act, record, repeat. All the
judgement lives in `plan_startup`, which is pure and therefore testable against
timeouts and partial fills without a network.

```text
while not settled:
    observation = broker.observe()          <- ALWAYS fresh, never cached
    plan        = plan_startup(...)         <- pure
    execute(plan)                           <- cancel / close
    store.append(plan.next_state)           <- durable, append-only
```

**Every iteration re-reads the broker.** Not an optimisation left undone — it is
the correctness property. The account is the only authority on what is held and
what is working, and a plan computed from a stale view is exactly how a duplicate
close gets submitted after a timeout.

**Transport failures do not advance the state.** If a close raises, the state is
not recorded and the next iteration re-observes. That is what makes the
"submitted, then the API timed out, and we do not know whether it was accepted"
case safe: the broker is asked rather than guessed at.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from sentinel.broker import SentinelBroker
from sentinel.ownership import (
    AccountObservation,
    LIQUIDATION_REASON,
    OwnershipState,
    Plan,
    plan_startup,
)
from sentinel.store import (
    OwnershipStore,
    current_state,
    ownership_established,
    record,
)

log = logging.getLogger(__name__)

#: How many observe/act cycles before giving up. A liquidation that has not
#: settled after this many passes is not going to settle by trying harder — the
#: market is closed, a symbol is halted, or something is wrong that a human needs
#: to see. Bounded rather than infinite so a stuck migration surfaces as a
#: refusal instead of a process that looks busy forever.
DEFAULT_MAX_CYCLES = 40

#: Seconds between cycles while orders are working.
DEFAULT_POLL_SECONDS = 5.0


@dataclass
class StartupResult:
    state: OwnershipState
    cycles: int
    bootstrap_allowed: bool
    detail: str = ""


class OwnershipNotEstablished(RuntimeError):
    """Raised when the account could not be brought to a clean handover.

    Wealth Core must not bootstrap onto an account whose ownership is unresolved:
    the legacy book would be indistinguishable from its own, and the first
    reconciliation would either adopt positions it never chose or sell positions
    it did.
    """


async def establish_ownership(
    *,
    broker: SentinelBroker,
    store: OwnershipStore,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep=asyncio.sleep,
) -> StartupResult:
    """Bring the paper account to `SENTINEL_OWNERSHIP_ESTABLISHED`.

    Idempotent. Calling it on an account Sentinel already owns is a no-op that
    returns immediately without reading a single position as legacy.
    """
    established = ownership_established(store)
    if established:
        # The short-circuit is not merely an optimisation — it is the invariant.
        # Anything below this line may decide to liquidate.
        log.info("sentinel: ownership already established; skipping legacy cleanup")
        return StartupResult(
            state=OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
            cycles=0,
            bootstrap_allowed=True,
            detail="ownership previously established",
        )

    state = current_state(store)
    last_plan: Optional[Plan] = None

    for cycle in range(1, max_cycles + 1):
        observation = await broker.observe()
        plan = plan_startup(
            state=state,
            observation=observation,
            ownership_established=ownership_established(store),
        )
        last_plan = plan
        log.info(
            "sentinel: cycle=%d state=%s -> %s (%s)",
            cycle, state.value, plan.next_state.value, plan.reason,
        )

        await _execute(broker, plan, observation)

        # Recorded only AFTER the actions succeeded. A state written first would
        # claim progress a raised transport error just disproved.
        record(store, plan.next_state, reason=plan.reason,
               cancelled=len(plan.cancel_order_ids),
               liquidated=list(plan.liquidate_tickers))
        state = plan.next_state

        if state is OwnershipState.FLAT_CONFIRMED:
            # Two events, not one. Flatness is observed; ownership is decided.
            # See sentinel/ownership.py for why conflating them re-arms legacy
            # cleanup the first time a Wealth Core book goes naturally flat.
            record(store, OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED,
                   reason="legacy book removed and account observed flat")
            record(store, OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
                   reason="ownership established")
            return StartupResult(
                state=OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
                cycles=cycle,
                bootstrap_allowed=True,
                detail=plan.reason,
            )

        if state is OwnershipState.LIQUIDATION_PENDING:
            await sleep(poll_seconds)

    raise OwnershipNotEstablished(
        f"account not flat after {max_cycles} cycles; last state {state.value} "
        f"({last_plan.reason if last_plan else 'no plan'}). Wealth Core is NOT "
        f"bootstrapped: a legacy book that will not close is a condition for a "
        f"human, not something to trade around."
    )


async def _execute(
    broker: SentinelBroker, plan: Plan, observation: AccountObservation
) -> None:
    if plan.cancel_order_ids:
        n = await broker.cancel_orders(plan.cancel_order_ids)
        log.info("sentinel: cancelled %d/%d legacy orders", n, len(plan.cancel_order_ids))

    for ticker in plan.liquidate_tickers:
        result = await broker.close_position(ticker)
        if not result.accepted:
            # Not fatal on its own: one symbol may be halted while the rest close
            # fine. The next cycle re-observes and retries whatever is still held,
            # so a transient refusal costs a poll interval rather than the run.
            log.warning(
                "sentinel: %s close REFUSED for %s: %s",
                LIQUIDATION_REASON, ticker, result.error,
            )
        else:
            log.info(
                "sentinel: %s close accepted for %s (order=%s status=%s)",
                LIQUIDATION_REASON, ticker, result.broker_order_id, result.status,
            )
