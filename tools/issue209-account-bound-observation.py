from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "sentinel/execution/contract.py",
    '''    instrument_identity: bool = False
    market_on_open: bool = False''',
    '''    instrument_identity: bool = False
    account_bound_observation: bool = False
    market_on_open: bool = False''')

replace_once(
    "sentinel/execution/contract.py",
    '''    terminal_recovery_through: Optional[datetime] = None

    def __post_init__(self) -> None:
        if (self.terminal_recovery_through is not None''',
    '''    terminal_recovery_through: Optional[datetime] = None
    #: Exact broker account under which this multi-request observation was read.
    #: Certified adapters declaring ``account_bound_observation`` must populate
    #: it and prove that identity stayed stable throughout the snapshot.
    account_identity: Optional[BrokerAccountIdentity] = None

    def __post_init__(self) -> None:
        if self.account_identity is not None:
            if (not self.account_identity.broker
                    or not self.account_identity.account_id):
                raise ValueError(
                    "BrokerObservation account identity must be complete")
        if (self.terminal_recovery_through is not None''')

replace_once(
    "sentinel/execution/alpaca.py",
    '''        recent_fill_history=True,
        instrument_identity=True,
        fractional_quantities=False,''',
    '''        recent_fill_history=True,
        instrument_identity=True,
        account_bound_observation=True,
        fractional_quantities=False,''')

replace_once(
    "sentinel/execution/alpaca.py",
    '''    async def _observe_snapshot(
            self, *, terminal_floor: Optional[datetime] = None,
            recovery_through: Optional[datetime] = None) -> BrokerObservation:
        opened, complete_open_a = await self._list_open_orders()
        terminal_a: list[BrokerOrder] = []
        complete_terminal_a = True
        if terminal_floor is not None:
            terminal_a, complete_terminal_a = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        orders, merged_a = _merge_order_sets(opened, terminal_a)
        positions = await self._list_positions()
        reopened, complete_open_b = await self._list_open_orders()
        terminal_b: list[BrokerOrder] = []
        complete_terminal_b = True
        if terminal_floor is not None:
            terminal_b, complete_terminal_b = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        recheck, merged_b = _merge_order_sets(reopened, terminal_b)
        completeness = Completeness.COMPLETE
        if not (complete_open_a and complete_open_b
                and complete_terminal_a and complete_terminal_b):
            completeness = Completeness.TRUNCATED
        elif (not merged_a or not merged_b
              or _fingerprint(recheck) != _fingerprint(orders)):
            completeness = Completeness.INCONSISTENT
        return BrokerObservation(
            observed_at=datetime.now(timezone.utc), orders=tuple(recheck),
            positions=tuple(positions), completeness=completeness,
            terminal_recovery_through=recovery_through)''',
    '''    async def _observe_snapshot(
            self, *, terminal_floor: Optional[datetime] = None,
            recovery_through: Optional[datetime] = None) -> BrokerObservation:
        # Account identity is part of the snapshot, not an adjacent fact. Check
        # it around each major phase so an A->B->A routing/credential flip is
        # detected before any observation can reach the journal.
        account_before = await self.identify_account()
        opened, complete_open_a = await self._list_open_orders()
        terminal_a: list[BrokerOrder] = []
        complete_terminal_a = True
        if terminal_floor is not None:
            terminal_a, complete_terminal_a = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        account_after_orders = await self.identify_account()
        positions = await self._list_positions()
        account_after_positions = await self.identify_account()
        reopened, complete_open_b = await self._list_open_orders()
        terminal_b: list[BrokerOrder] = []
        complete_terminal_b = True
        if terminal_floor is not None:
            terminal_b, complete_terminal_b = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        account_after = await self.identify_account()
        accounts = (
            account_before, account_after_orders,
            account_after_positions, account_after)
        identity_keys = {(item.broker, item.account_id) for item in accounts}
        if len(identity_keys) != 1:
            raise MalformedBrokerPayload(
                "Alpaca account identity changed during one broker observation: "
                + ", ".join(f"{b}/{a}" for b, a in sorted(identity_keys)))
        orders, merged_a = _merge_order_sets(opened, terminal_a)
        recheck, merged_b = _merge_order_sets(reopened, terminal_b)
        completeness = Completeness.COMPLETE
        if not (complete_open_a and complete_open_b
                and complete_terminal_a and complete_terminal_b):
            completeness = Completeness.TRUNCATED
        elif (not merged_a or not merged_b
              or _fingerprint(recheck) != _fingerprint(orders)):
            completeness = Completeness.INCONSISTENT
        return BrokerObservation(
            observed_at=datetime.now(timezone.utc), orders=tuple(recheck),
            positions=tuple(positions), completeness=completeness,
            terminal_recovery_through=recovery_through,
            account_identity=account_before)''')

replace_once(
    "sentinel/execution/simulator.py",
    '''            recent_fill_history=True, instrument_identity=True,
            market_on_open=True))''',
    '''            recent_fill_history=True, instrument_identity=True,
            account_bound_observation=True, market_on_open=True))''')
replace_once(
    "sentinel/execution/simulator.py",
    '''        return BrokerObservation(observed_at=self.now, orders=orders,
                                 positions=positions, completeness=completeness)''',
    '''        return BrokerObservation(
            observed_at=self.now, orders=orders, positions=positions,
            completeness=completeness, account_identity=self.account)''')

replace_once(
    "sentinel/execution/reconcile.py",
    '''    observation_seq = journal.record_observation(
        conn, observation, RuntimeState.RECONCILING.value)

    if not observation.is_complete:''',
    '''    # A certified account-bound observation may mutate command history only
    # after the exact observation itself is proven to belong to the durable
    # binding. The earlier identify_account() call is not a substitute: routing
    # can flip during the multi-request orders/positions snapshot.
    if getattr(broker.capabilities, "account_bound_observation", False):
        observed_identity = observation.account_identity
        if observed_identity is None:
            return ReconciliationResult(
                runtime_state=RuntimeState.BROKER_DEGRADED,
                observation=observation,
                detail="certified broker observation omitted account provenance")
        try:
            binding_mod.verify(conn, observed_identity)
        except Exception as exc:                              # noqa: BLE001
            return ReconciliationResult(
                runtime_state=RuntimeState.BROKER_DEGRADED,
                observation=observation,
                detail=f"broker observation account provenance refused: {exc}")
        if ((observed_identity.broker, observed_identity.account_id)
                != (identity.broker, identity.account_id)):
            return ReconciliationResult(
                runtime_state=RuntimeState.BROKER_DEGRADED,
                observation=observation,
                detail="broker identity changed between reconciliation and "
                       "the account-bound observation")

    observation_seq = journal.record_observation(
        conn, observation, RuntimeState.RECONCILING.value)

    if not observation.is_complete:''')

replace_once(
    "sentinel/execution/journal.py",
    '''        seq = int(cur.fetchone()[0])
    conn.commit()
    return seq''',
    '''        seq = int(cur.fetchone()[0])
        if observation.account_identity is not None:
            cur.execute(
                "INSERT INTO sentinel_observation_provenance"
                " (observation_seq,broker,broker_account_id,observed_at)"
                " VALUES (%s,%s,%s,%s)",
                (seq, observation.account_identity.broker,
                 observation.account_identity.account_id,
                 observation.observed_at))
    conn.commit()
    return seq''')

replace_once(
    "sentinel/schema.py",
    '''    "sentinel_automation_service_instances",
})''',
    '''    "sentinel_automation_service_instances",
    "sentinel_observation_provenance",
})''')
replace_once(
    "sentinel/schema.py",
    '''    """ALTER TABLE sentinel_observations
        ADD COLUMN IF NOT EXISTS terminal_recovery_through TIMESTAMPTZ""",

    # A broker response being durable is not proof that it was PROCESSED.''',
    '''    """ALTER TABLE sentinel_observations
        ADD COLUMN IF NOT EXISTS terminal_recovery_through TIMESTAMPTZ""",
    # Additive Stage-4 provenance avoids rewriting the core behavioral catalog
    # while binding each new authority-bearing observation to its broker account.
    """CREATE TABLE IF NOT EXISTS sentinel_observation_provenance (
        observation_seq   BIGINT PRIMARY KEY REFERENCES sentinel_observations(seq),
        broker            TEXT        NOT NULL,
        broker_account_id TEXT        NOT NULL,
        observed_at       TIMESTAMPTZ NOT NULL)""",

    # A broker response being durable is not proof that it was PROCESSED.''')

Path("tests/sentinel/test_issue209_account_bound_observation.py").write_text(r'''import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution.alpaca import AlpacaExecutionBroker, MalformedBrokerPayload
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerCapabilities, BrokerObservation, Completeness,
)
from sentinel.execution.reconcile import ReconciliationResult


PAPER = "https://paper-api.alpaca.markets"


def _broker():
    return AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url=PAPER,
        resolve_security_id=lambda symbol, _as_of=None: symbol,
        http_provider=lambda: None)


def test_alpaca_observation_refuses_a_b_a_account_flip():
    broker = _broker()
    identities = iter([
        BrokerAccountIdentity("alpaca", "A"),
        BrokerAccountIdentity("alpaca", "B"),
        BrokerAccountIdentity("alpaca", "A"),
        BrokerAccountIdentity("alpaca", "A"),
    ])

    async def identity():
        return next(identities)

    async def open_orders():
        return [], True

    async def positions():
        return []

    broker.identify_account = identity
    broker._list_open_orders = open_orders  # noqa: SLF001
    broker._list_positions = positions  # noqa: SLF001

    with pytest.raises(MalformedBrokerPayload, match="changed during"):
        asyncio.run(broker._observe_snapshot())  # noqa: SLF001


def test_stable_alpaca_observation_carries_account_identity():
    broker = _broker()
    account = BrokerAccountIdentity("alpaca", "A")

    async def identity():
        return account

    async def open_orders():
        return [], True

    async def positions():
        return []

    broker.identify_account = identity
    broker._list_open_orders = open_orders  # noqa: SLF001
    broker._list_positions = positions  # noqa: SLF001
    observed = asyncio.run(broker._observe_snapshot())  # noqa: SLF001
    assert observed.completeness is Completeness.COMPLETE
    assert observed.account_identity == account
    assert broker.capabilities.account_bound_observation is True
''', encoding="utf-8")
