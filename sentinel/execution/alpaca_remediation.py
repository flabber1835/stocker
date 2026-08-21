"""Focused hardening overlay for the Alpaca execution boundary.

This module exists because the broker contract has a few properties that cannot
be represented by Alpaca's raw REST shapes alone.  The installed classes remain
normal subclasses of the reviewed execution adapters; the overlay only adds
proofs/evidence and never changes portfolio intent.

It closes the post-#183 wire-compatibility finding and the locally enforceable
parts of #110/#124/#127/#128/#129/#131/#146.  #125 deliberately remains a
broker-primitive limitation: a syntactically valid list response that silently
omits an *unknown post-backup order* has no independent completeness witness in
Alpaca's Trading API.  This module does not manufacture one.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Sequence
from urllib.parse import quote

_INSTALLED = False
_AUTOMATION_SERIALIZATION_INSTALLED = False


@contextmanager
def _authority_transition_lock(conn):
    """Linearize emergency authority changes with broker mutation."""
    from sentinel.execution import journal

    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (journal.WRITER_LOCK_KEY,))
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (journal.WRITER_LOCK_KEY,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def install_automation_serialization() -> bool:
    """Install authority fencing after ``automation.store`` is initialized.

    ``automation.store`` imports ``execution.journal``. Importing the execution
    package installs this overlay, so eagerly dereferencing ``engage_kill`` here
    used to observe a half-built module and made the unattended service fail at
    collection/startup. The store calls this hook again at the end of its own
    module; ordinary execution-first imports also call it from :func:`install`.
    """
    global _AUTOMATION_SERIALIZATION_INSTALLED
    if _AUTOMATION_SERIALIZATION_INSTALLED:
        return True

    from sentinel.automation import store as automation_store
    if not hasattr(automation_store, "engage_kill"):
        return False
    from sentinel import authority

    original_engage_kill = automation_store.engage_kill

    def serialized_engage_kill(conn, *, actor: str, reason: str):
        with _authority_transition_lock(conn):
            return original_engage_kill(conn, actor=actor, reason=reason)

    automation_store.engage_kill = serialized_engage_kill

    def serialize_authority_function(function):
        def serialized(conn, *args, **kwargs):
            with _authority_transition_lock(conn):
                return function(conn, *args, **kwargs)
        serialized.__name__ = function.__name__
        serialized.__doc__ = function.__doc__
        return serialized

    authority.revoke_signed_certificate = serialize_authority_function(
        authority.revoke_signed_certificate)
    authority.revoke_signed_key = serialize_authority_function(
        authority.revoke_signed_key)
    authority.revoke_system_certificate = serialize_authority_function(
        authority.revoke_system_certificate)
    _AUTOMATION_SERIALIZATION_INSTALLED = True
    return True


def install() -> None:
    """Install the hardened broker/evidence classes exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    from sentinel.execution import alpaca as alpaca
    from sentinel.execution import guarded as guarded
    from sentinel.execution import journal
    from sentinel.execution import reconcile
    from sentinel.execution import contract
    from sentinel.execution.broker_cash import (
        BrokerCashActivity,
        BrokerCashActivityBatch,
        RECOGNIZED_ACTIVITY_TYPES,
    )

    if getattr(alpaca, "_BOUNDARY_REMEDIATION_INSTALLED", False):
        _INSTALLED = True
        return

    @dataclass(frozen=True)
    class AccountBoundObservation(contract.BrokerObservation):
        """Observation carrying the account identity that bracketed its reads."""

        account_identity: Optional[contract.BrokerAccountIdentity] = None

        def __post_init__(self) -> None:
            super().__post_init__()
            if self.account_identity is not None:
                if (not self.account_identity.broker
                        or not self.account_identity.account_id):
                    raise ValueError("account-bound observation identity is incomplete")

    @dataclass(frozen=True)
    class NativeBrokerFill(contract.BrokerFill):
        """Fill whose broker-native activity id is the idempotency authority."""

        activity_id: Optional[str] = None

        def __post_init__(self) -> None:
            super().__post_init__()
            if self.activity_id is not None and not str(self.activity_id).strip():
                raise ValueError("native fill activity id must be non-empty")

    OriginalAlpaca = alpaca.AlpacaExecutionBroker

    class HardenedAlpacaExecutionBroker(OriginalAlpaca):
        """Alpaca adapter with account, asset and activity evidence tightened."""

        def _validate_submit_response(
                self, payload, *, client_key: str,
                instrument: contract.BrokerInstrument,
                side: contract.Side, quantity: Decimal):
            # Alpaca represents a simple order as either "" or "simple".  PR
            # #184's validator accepted only the latter, turning a valid 2xx into
            # false uncertainty.  Normalize only this documented equivalence;
            # bracket/oco/oto values still fail closed in the original validator.
            if isinstance(payload, dict) and payload.get("order_class") == "":
                payload = dict(payload)
                payload["order_class"] = "simple"
            return super()._validate_submit_response(
                payload, client_key=client_key, instrument=instrument,
                side=side, quantity=quantity)

        async def account_cash_activities(
                self, *, after: datetime,
                through: datetime) -> BrokerCashActivityBatch:
            floor = alpaca._required_aware_ts(
                after, where="cash activity lower boundary")
            upper = alpaca._required_aware_ts(
                through, where="cash activity upper boundary")
            if floor > upper:
                raise alpaca.MalformedBrokerPayload(
                    "cash activity lower boundary is later than upper boundary")

            activities: list[BrokerCashActivity] = []
            seen_ids: set[str] = set()
            page_token: Optional[str] = None
            last_recognized_id: Optional[str] = None
            for _page in range(alpaca.MAX_ACTIVITY_PAGES):
                # Category, not a fixed activity-type allowlist.  A vendor-added
                # non-zero cash type must reach Sentinel and become a refusal;
                # filtering it at the request would make the negative space
                # unknowable and could defeat cash authority.
                params = {
                    "category": "non_trade_activity",
                    "after": floor.isoformat(),
                    "until": upper.isoformat(),
                    "direction": "asc",
                    "page_size": alpaca.ACTIVITY_PAGE_SIZE,
                }
                if page_token:
                    params["page_token"] = page_token
                page = await self._get("/v2/account/activities", params)
                if not isinstance(page, list):
                    raise alpaca.MalformedBrokerPayload(
                        "account-activities response must be an array")
                if len(page) > alpaca.ACTIVITY_PAGE_SIZE:
                    raise alpaca.MalformedBrokerPayload(
                        "account-activities page exceeds requested page size")
                if not page:
                    return BrokerCashActivityBatch(
                        activities=tuple(activities), processed_through=upper,
                        completeness=contract.Completeness.COMPLETE,
                        last_activity_id=last_recognized_id)

                page_ids: list[str] = []
                for item in page:
                    if not isinstance(item, dict):
                        raise alpaca.MalformedBrokerPayload(
                            "account-activities page contains a non-object row")
                    activity_id = str(item.get("id") or "").strip()
                    if not activity_id:
                        raise alpaca.MalformedBrokerPayload(
                            "account activity row has no native activity id")
                    if activity_id in seen_ids:
                        raise alpaca.MalformedBrokerPayload(
                            "account-activities pagination repeated native id "
                            f"{activity_id}")
                    seen_ids.add(activity_id)
                    page_ids.append(activity_id)
                    activity_type = str(
                        item.get("activity_type") or "").upper()
                    amount = alpaca._required_dec(
                        item.get("net_amount"),
                        where=f"account activity {activity_id} net_amount",
                        allow_negative=True)
                    if activity_type not in RECOGNIZED_ACTIVITY_TYPES:
                        if amount == 0:
                            # A non-cash corporate event is outside this cash
                            # ledger. Its native id still participates in page
                            # progress, but it does not pretend to be cash.
                            continue
                        raise alpaca.MalformedBrokerPayload(
                            "unrecognized non-trade cash activity "
                            f"{activity_id}: type={activity_type!r}, "
                            f"net_amount={amount}")
                    try:
                        activity_date = date.fromisoformat(
                            str(item.get("date") or "")[:10])
                    except ValueError:
                        raise alpaca.MalformedBrokerPayload(
                            f"account activity {activity_id} has invalid date "
                            f"{item.get('date')!r}") from None
                    activities.append(BrokerCashActivity(
                        activity_id=activity_id,
                        activity_type=activity_type,
                        activity_date=activity_date,
                        net_amount=amount,
                        raw=item,
                    ))
                    last_recognized_id = activity_id

                if len(page) < alpaca.ACTIVITY_PAGE_SIZE:
                    return BrokerCashActivityBatch(
                        activities=tuple(activities), processed_through=upper,
                        completeness=contract.Completeness.COMPLETE,
                        last_activity_id=last_recognized_id)
                next_token = page_ids[-1]
                if not next_token or next_token == page_token:
                    return BrokerCashActivityBatch(
                        activities=tuple(activities), processed_through=upper,
                        completeness=contract.Completeness.TRUNCATED,
                        last_activity_id=last_recognized_id)
                page_token = next_token

            return BrokerCashActivityBatch(
                activities=tuple(activities), processed_through=upper,
                completeness=contract.Completeness.TRUNCATED,
                last_activity_id=last_recognized_id)

        async def _recent_fills_bounded(
                self, since: datetime,
                through: Optional[datetime]) -> Sequence[contract.BrokerFill]:
            floor = alpaca._required_aware_ts(
                since, where="fill activity lower boundary")
            upper = (alpaca._required_aware_ts(
                through, where="fill activity upper boundary")
                     if through is not None else None)
            if upper is not None and floor > upper:
                raise alpaca.MalformedBrokerPayload(
                    "fill activity lower boundary is later than upper boundary")
            out: list[contract.BrokerFill] = []
            seen_ids: set[str] = set()
            page_token: Optional[str] = None
            for _page in range(alpaca.MAX_ACTIVITY_PAGES):
                params = {
                    "after": floor.isoformat(),
                    "direction": "asc",
                    "page_size": alpaca.ACTIVITY_PAGE_SIZE,
                }
                if upper is not None:
                    params["until"] = upper.isoformat()
                if page_token:
                    params["page_token"] = page_token
                page = await self._get("/v2/account/activities/FILL", params)
                if not isinstance(page, list):
                    raise alpaca.MalformedBrokerPayload(
                        "fill activities response must be an array")
                if len(page) > alpaca.ACTIVITY_PAGE_SIZE:
                    raise alpaca.MalformedBrokerPayload(
                        "fill activities page exceeds requested page size")
                if not page:
                    return tuple(out)
                page_ids: list[str] = []
                for item in page:
                    if not isinstance(item, dict):
                        raise alpaca.MalformedBrokerPayload(
                            "fill activities page contains a non-object row")
                    activity_id = str(item.get("id") or "").strip()
                    if not activity_id:
                        raise alpaca.MalformedBrokerPayload(
                            "fill activity has no broker-native id")
                    if activity_id in seen_ids:
                        raise alpaca.MalformedBrokerPayload(
                            "fill activity pagination repeated native id "
                            f"{activity_id}")
                    seen_ids.add(activity_id)
                    page_ids.append(activity_id)
                    broker_order_id = str(item.get("order_id") or "").strip()
                    if not broker_order_id:
                        raise alpaca.MalformedBrokerPayload(
                            f"fill activity {activity_id} omitted order_id")
                    out.append(NativeBrokerFill(
                        activity_id=activity_id,
                        client_key=None,
                        broker_order_id=broker_order_id,
                        quantity=alpaca._required_dec(
                            item.get("qty"),
                            where=f"activity {activity_id} qty"),
                        price=alpaca._required_dec(
                            item.get("price"),
                            where=f"activity {activity_id} price"),
                        filled_at=alpaca._parse_ts(
                            item.get("transaction_time")),
                    ))
                if len(page) < alpaca.ACTIVITY_PAGE_SIZE:
                    return tuple(out)
                next_token = page_ids[-1]
                if not next_token or next_token == page_token:
                    raise alpaca.MalformedBrokerPayload(
                        "fill activity pagination cannot prove completeness")
                page_token = next_token
            raise alpaca.MalformedBrokerPayload(
                "fill activity traversal hit its page cap; refusing to imply "
                "complete recovery history")

        async def recent_fills(
                self, since: datetime) -> Sequence[contract.BrokerFill]:
            return await self._recent_fills_bounded(since, None)

        async def _observe_snapshot(
                self, *, terminal_floor: Optional[datetime] = None,
                recovery_through: Optional[datetime] = None):
            # The base adapter already binds ordinary snapshots with identity
            # reads around every major phase.  This overlay needs an additional
            # outer fence only when it adds fill-activity recovery work.
            if terminal_floor is None:
                return await super()._observe_snapshot(
                    terminal_floor=terminal_floor,
                    recovery_through=recovery_through)
            account_before = await self.identify_account()
            observed = await super()._observe_snapshot(
                terminal_floor=terminal_floor,
                recovery_through=recovery_through)

            # A fill activity is keyed to when the economic event occurred, not
            # to the order's ancient submitted_at.  Join a newly reported fill
            # back to its exact order so a CANCELLED/FILLED command cannot age
            # out of closed-order pagination and then mutate silently (#127).
            orders = list(observed.orders)
            known_order_ids = {o.broker_order_id for o in orders}
            if terminal_floor is not None:
                fills = await self._recent_fills_bounded(
                    terminal_floor, recovery_through)
                for fill in fills:
                    if fill.broker_order_id in known_order_ids:
                        continue
                    payload = await self._get(
                        f"/v2/orders/{quote(fill.broker_order_id, safe='')}")
                    if not isinstance(payload, dict):
                        raise alpaca.MalformedBrokerPayload(
                            "late-fill exact order lookup returned no order object")
                    order = self._to_order(payload)
                    if order.broker_order_id != fill.broker_order_id:
                        raise alpaca.MalformedBrokerPayload(
                            "late-fill exact order lookup changed broker order id")
                    orders.append(order)
                    known_order_ids.add(order.broker_order_id)

            account_after = await self.identify_account()
            completeness = observed.completeness
            if (account_after.broker != account_before.broker
                    or account_after.account_id != account_before.account_id):
                completeness = contract.Completeness.INCONSISTENT

            return AccountBoundObservation(
                observed_at=observed.observed_at,
                orders=tuple(orders),
                positions=tuple(observed.positions),
                completeness=completeness,
                terminal_recovery_through=observed.terminal_recovery_through,
                account_identity=account_before,
            )

    # Stable broker identity participates in the two-read stability fingerprint.
    def hardened_order_fingerprint(orders) -> tuple:
        return tuple(sorted((
            o.broker_order_id,
            o.client_key or "",
            o.instrument.security_id,
            o.instrument.broker_id or "",
            o.side.value,
            str(o.quantity),
            o.state.value,
            str(o.filled_quantity),
            (str(o.filled_average_price)
             if o.filled_average_price is not None else ""),
            (o.submitted_at.isoformat() if o.submitted_at is not None else ""),
        ) for o in orders))

    alpaca.AlpacaExecutionBroker = HardenedAlpacaExecutionBroker
    alpaca._fingerprint = hardened_order_fingerprint
    alpaca.AccountBoundObservation = AccountBoundObservation
    alpaca.NativeBrokerFill = NativeBrokerFill

    # Re-resolve symbol -> Alpaca asset id after clock corroboration and before
    # the final mutation-authority callback. The callback then returns directly
    # into POST with no intervening await.
    OriginalGuarded = guarded.GuardedExecutionBroker

    class HardenedGuardedExecutionBroker(OriginalGuarded):
        async def submit(
                self, *, client_key: str,
                instrument: contract.BrokerInstrument,
                side: contract.Side,
                quantity: Decimal) -> contract.CommandOutcome:
            if (isinstance(self._grant, guarded.PaperPreparationGrant)
                    or (isinstance(self._grant, guarded.AutomationExecutionGrant)
                        and self._grant.operation_scope != "EXECUTE")):
                raise guarded.PreTransportAuthorityRefused(
                    "preparation grant is read-only; submit refused before transport")

            if side is contract.Side.BUY and self.supports_market_clock:
                try:
                    clock = await self.market_clock()
                except guarded.BrokerAuthorityRefused as exc:
                    raise guarded.PreTransportAuthorityRefused(
                        f"broker clock authority unavailable before increase: {exc}") from exc
                except Exception as exc:
                    raise guarded.PreTransportAuthorityRefused(
                        "broker clock unavailable before increase: "
                        f"{type(exc).__name__}: {exc}") from exc
                if getattr(clock, "is_open", None) is not True:
                    raise guarded.PreTransportAuthorityRefused(
                        "broker clock reports market closed; increase refused "
                        "before transport")

            # Stable asset-id re-resolution is an Alpaca transport invariant,
            # not a new requirement on every broker that advertises a generic
            # instrument-identity capability. Simulator and future adapters
            # retain their own conformance contracts.
            if (isinstance(self._inner, alpaca.AlpacaExecutionBroker)
                    and self.capabilities.instrument_identity):
                if not instrument.broker_id:
                    raise guarded.PreTransportAuthorityRefused(
                        "durable command has no broker-native instrument identity")
                try:
                    current = await self.resolve_instrument(
                        security_id=instrument.security_id,
                        symbol=instrument.symbol)
                except guarded.BrokerAuthorityRefused as exc:
                    raise guarded.PreTransportAuthorityRefused(
                        f"instrument identity unavailable before submit: {exc}") from exc
                except Exception as exc:
                    raise guarded.PreTransportAuthorityRefused(
                        "instrument identity unavailable before submit: "
                        f"{type(exc).__name__}: {exc}") from exc
                if (current.security_id != instrument.security_id
                        or current.symbol != instrument.symbol
                        or current.broker_id != instrument.broker_id):
                    raise guarded.PreTransportAuthorityRefused(
                        "broker-native instrument identity changed before submit; "
                        f"durable={instrument}, current={current}")

            await self._authorize_mutation(guarded.BrokerOperation.SUBMIT)
            return await self._inner.submit(
                client_key=client_key,
                instrument=instrument,
                side=side,
                quantity=quantity,
            )

    guarded.GuardedExecutionBroker = HardenedGuardedExecutionBroker

    # Exact-key evidence and reconciliation both reject an asset-id substitution.
    original_conflict = reconcile._order_command_conflict

    def hardened_order_command_conflict(order, command):
        conflict = original_conflict(order, command)
        if conflict:
            return conflict
        if (command.instrument.broker_id is not None
                and order.instrument.broker_id != command.instrument.broker_id):
            return (
                f"broker order {order.broker_order_id}/{order.client_key} "
                "changed durable broker instrument "
                f"{command.instrument.broker_id!r} to "
                f"{order.instrument.broker_id!r}")
        return None

    reconcile._order_command_conflict = hardened_order_command_conflict

    def hardened_reconcile_fingerprint(order) -> tuple:
        return (
            order.broker_order_id,
            order.client_key,
            order.instrument.security_id,
            order.instrument.broker_id,
            order.side,
            order.quantity,
            order.state,
            order.filled_quantity,
            order.filled_average_price,
        )

    reconcile._order_observation_fingerprint = hardened_reconcile_fingerprint

    # A broker observation may not enter durable command history if its own
    # account bracket disagrees with the PostgreSQL account binding (#128).
    original_record_observation = journal.record_observation

    def record_account_bound_observation(conn, observation, runtime_state=""):
        account_identity = getattr(observation, "account_identity", None)
        if account_identity is not None:
            broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
            if (account_identity.broker != broker_name
                    or account_identity.account_id != account_id):
                raise RuntimeError(
                    "broker observation account identity does not match the "
                    "durable account binding; refusing journal mutation")
        return original_record_observation(conn, observation, runtime_state)

    journal.record_observation = record_account_bound_observation

    # Native fill activity id is the exact event identity.  The content hash is
    # retained only for pre-upgrade/non-native fills.
    original_fill_fingerprint = journal.fill_fingerprint

    def native_fill_fingerprint(fill) -> str:
        activity_id = getattr(fill, "activity_id", None)
        if activity_id:
            payload = {
                "kind": "broker-native-fill/v1",
                "activity_id": str(activity_id),
            }
            return hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
                .encode("utf-8")).hexdigest()
        return original_fill_fingerprint(fill)

    journal.fill_fingerprint = native_fill_fingerprint

    # Terminal-recovery watermark integrity witness (#146).  The witness is
    # derived only from an exact COMPLETE observation with the same bounded
    # upper instant. It is committed atomically with the watermark.
    WITNESS_PREFIX = "terminal-recovery-witness:v1:"

    def witness_name(broker_name: str, account_id: str) -> str:
        return f"{WITNESS_PREFIX}{broker_name}:{account_id}"

    def observation_witness(conn, through: datetime):
        through = journal._aware_utc(through, "terminal recovery witness")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT seq,observed_at,terminal_recovery_through,"
                " completeness,positions,orders"
                " FROM sentinel_observations"
                " WHERE terminal_recovery_through=%s"
                " AND completeness='COMPLETE'"
                " ORDER BY seq DESC LIMIT 1",
                (through,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        payload = {
            "seq": int(row[0]),
            "observed_at": journal._aware_utc(
                row[1], "broker observation").isoformat(),
            "processed_through": journal._aware_utc(
                row[2], "broker observation boundary").isoformat(),
            "completeness": str(row[3]),
            "positions": row[4],
            "orders": row[5],
        }
        digest = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str)
            .encode("utf-8")).hexdigest()
        return int(row[0]), digest

    def hardened_terminal_checkpoint(conn) -> datetime:
        broker_name, account_id, established_at = (
            journal._terminal_recovery_binding(conn))
        with conn.cursor() as cur:
            cur.execute(
                "SELECT broker,broker_account_id,processed_through"
                " FROM sentinel_terminal_recovery_watermark WHERE id=1")
            row = cur.fetchone()
        if row is None:
            return established_at
        if str(row[0]) != broker_name or str(row[1]) != account_id:
            raise RuntimeError(
                "terminal recovery watermark belongs to another account")
        if row[2] is None:
            raise RuntimeError(
                "terminal recovery watermark has no processed boundary")
        processed = journal._aware_utc(
            row[2], "terminal recovery checkpoint")
        observed = observation_witness(conn, processed)
        if observed is None:
            raise RuntimeError(
                "terminal recovery watermark has no exact COMPLETE broker "
                "observation; refusing to narrow recovery history")
        observation_seq, observation_sha = observed
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s",
                (witness_name(broker_name, account_id),),
            )
            witness_row = cur.fetchone()
        if witness_row is not None:
            state = witness_row[0]
            if not isinstance(state, dict):
                try:
                    state = json.loads(str(state))
                except Exception as exc:
                    raise RuntimeError(
                        "terminal recovery witness is invalid JSON") from exc
            expected = {
                "kind": "terminal-recovery-witness/v1",
                "broker": broker_name,
                "account_id": account_id,
                "processed_through": processed.isoformat(),
                "observation_seq": observation_seq,
                "observation_sha256": observation_sha,
            }
            if state != expected:
                raise RuntimeError(
                    "terminal recovery watermark integrity witness disagrees "
                    "with its exact broker observation")
        # Legacy pre-witness watermarks are accepted only when their exact
        # COMPLETE observation survives. This is reconstruction from evidence,
        # not guessing; the next advancement writes the explicit witness.
        return processed

    def hardened_terminal_floor(conn) -> datetime:
        return (hardened_terminal_checkpoint(conn)
                - journal.TERMINAL_RECOVERY_OVERLAP)

    def hardened_advance_terminal_watermark(
            conn, through: datetime) -> datetime:
        candidate = journal._aware_utc(
            through, "terminal recovery upper boundary")
        current = hardened_terminal_checkpoint(conn)
        processed = max(current, candidate)
        broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
        observed = observation_witness(conn, processed)
        if observed is None:
            raise RuntimeError(
                "terminal recovery cannot advance without an exact COMPLETE "
                "broker observation at the processed boundary")
        observation_seq, observation_sha = observed
        state = {
            "kind": "terminal-recovery-witness/v1",
            "broker": broker_name,
            "account_id": account_id,
            "processed_through": processed.isoformat(),
            "observation_seq": observation_seq,
            "observation_sha256": observation_sha,
        }
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_terminal_recovery_watermark"
                " (id,broker,broker_account_id,processed_through)"
                " VALUES (1,%s,%s,%s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " processed_through=GREATEST("
                " sentinel_terminal_recovery_watermark.processed_through,"
                " EXCLUDED.processed_through),updated_at=NOW()",
                (broker_name, account_id, processed),
            )
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO UPDATE SET"
                " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
                (witness_name(broker_name, account_id),
                 processed.date().isoformat(),
                 json.dumps(state, sort_keys=True)),
            )
        conn.commit()
        return processed

    journal.terminal_recovery_checkpoint = hardened_terminal_checkpoint
    journal.terminal_recovery_floor = hardened_terminal_floor
    journal.advance_terminal_recovery_watermark = (
        hardened_advance_terminal_watermark)

    install_automation_serialization()

    alpaca._BOUNDARY_REMEDIATION_INSTALLED = True
    _INSTALLED = True


__all__ = ["install", "install_automation_serialization"]
