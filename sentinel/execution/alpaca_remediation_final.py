"""Final broker-boundary hardening layered over the issue-183 remediation.

This module closes the review gaps found on PR #196 without weakening the
existing fail-closed execution model:

* Alpaca orders are addressed by the durable ``asset_id`` rather than a ticker.
* ``broker_instrument_id`` is immutable under one deterministic client key.
* Activity SSE replaces legacy Account Activities REST for cash/fill evidence.
* account/broker-id provenance is retained for every Alpaca observation.
* terminal-recovery watermarks are accepted only with a completion witness that
  could be written after every discovered Sentinel order was durably reconciled.
* a PostgreSQL physical-restore/timeline change fences increases until an
  explicit takeover epoch acknowledges the restored incarnation; predecessor
  DAY orders also receive a full-session expiry fence before re-risking.

The remaining impossibility boundary is explicit rather than hidden: a broker
can always lie consistently across every endpoint. Sentinel requires the
strongest independent primitives Alpaca exposes and refuses contradictory or
incomplete evidence; it does not manufacture a cryptographic proof the broker
API does not provide.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Mapping, Optional, Sequence

_INSTALLED = False

_ACTIVITY_SSE_AVAILABLE_FROM = datetime(2026, 2, 11, tzinfo=timezone.utc)
_OBSERVATION_PREFIX = "broker-observation:v2:"
_WITNESS_PREFIX = "terminal-recovery-witness:v2:"
_DB_INCARCERATION_CURSOR = "broker-recovery-db-incarnation:v1"

# Activity SSE types documented by Alpaca as of 2026-08.  Unknown non-zero cash
# effects are a refusal, not a silently ignored vendor taxonomy addition.
_EXTERNAL_CASH_TYPES = frozenset({"CSD", "CSW", "ACATC", "MEM", "FOPT"})
_INTERNAL_CASH_TYPES = frozenset({
    "TRD", "DIV", "SPLIT", "SPIN", "MA", "NC", "REORG", "VOF", "FIMAT",
    "DIVNRA", "OPCA", "OPASN", "OPEXC", "OPEXP", "OPTRD", "OPCSH",
    "ACATS", "JNLC", "JNLS", "FEE", "INT", "WH",
    # Legacy spellings remain accepted during the upgrade overlap.
    "CFEE", "INTNRA", "INTTW", "JNL", "DIVCGL", "DIVCGS", "DIVFEE",
    "DIVFT", "DIVROC", "DIVTW", "DIVTXEX", "CGD", "PTC", "PTR",
})


class ActivityCorrectionRequiresRecovery(RuntimeError):
    """A correction/bust needs reversal semantics before trading may continue."""


class RestoreGradeIncreaseDeferred(RuntimeError):
    """A database takeover has not yet made predecessor DAY orders harmless."""


def _loads_state(raw, *, where: str) -> dict:
    if isinstance(raw, dict):
        value = raw
    else:
        try:
            value = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"{where} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{where} must be a JSON object")
    return value


def _sse_events(text: str, *, malformed) -> tuple[dict, ...]:
    """Parse a bounded Alpaca SSE response; comments that signal loss refuse."""
    events: list[dict] = []
    data: list[str] = []

    def flush() -> None:
        if not data:
            return
        payload = "\n".join(data)
        data.clear()
        try:
            event = json.loads(payload)
        except Exception as exc:
            raise malformed("Activity SSE contained malformed JSON") from exc
        if not isinstance(event, dict):
            raise malformed("Activity SSE data event must be a JSON object")
        events.append(event)

    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.startswith(":"):
            lowered = line.lower()
            if "dropped" in lowered or "internal server error" in lowered:
                raise malformed(
                    "Activity SSE reported message loss/server failure; "
                    "history is not complete")
            continue
        if line == "":
            flush()
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
            continue
        # event/id/retry fields are transport metadata. Unknown non-comment,
        # non-SSE fields are not ignored because doing so can hide corruption.
        if line.startswith(("event:", "id:", "retry:")):
            continue
        raise malformed(f"Activity SSE contained unknown line {line!r}")
    flush()
    return tuple(events)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from sentinel.execution import (
        alpaca, broker_cash, contract, executor, journal)
    from sentinel.execution import authority_gate
    from sentinel.execution.guarded import BrokerAuthorityRefused
    from sentinel.execution.identity import is_sentinel_key
    from sentinel.execution.states import CommandState

    if getattr(alpaca, "_FINAL_BOUNDARY_REMEDIATION_INSTALLED", False):
        _INSTALLED = True
        return

    # The fresh authority gate added ACCOUNT_CASH_ACTIVITIES to the broker port
    # but omitted it from its read-operation set. That turned the new cash proof
    # into an "unknown broker operation" at the production guard.
    authority_gate._READ_OPERATIONS = frozenset(
        set(authority_gate._READ_OPERATIONS)
        | {authority_gate.BrokerOperation.ACCOUNT_CASH_ACTIVITIES})

    # Teach the durable cash classifier the unified Activity-SSE vocabulary.
    broker_cash.EXTERNAL_ACTIVITY_TYPES = _EXTERNAL_CASH_TYPES
    broker_cash.INTERNAL_ACTIVITY_TYPES = _INTERNAL_CASH_TYPES
    broker_cash.RECOGNIZED_ACTIVITY_TYPES = (
        _EXTERNAL_CASH_TYPES | _INTERNAL_CASH_TYPES)

    CurrentAlpaca = alpaca.AlpacaExecutionBroker
    NativeBrokerFill = alpaca.NativeBrokerFill

    class FinancialGradeAlpacaExecutionBroker(CurrentAlpaca):
        """Alpaca adapter using stable asset identity and unified Activity SSE."""

        # The generic flag historically implied more than Alpaca can prove from
        # open-order REST enumeration after a stale restore. Ordinary pagination
        # remains usable, but restore-grade safety is supplied by the independent
        # DB-incarnation/DAY-order fence below, not by this claim.
        capabilities = replace(
            CurrentAlpaca.capabilities,
            complete_order_pagination=False,
            recent_fill_history=False,
        )
        restore_grade_order_recovery = False
        account_snapshot_freshness = False
        financial_activity_sse = True

        async def submit(
                self, *, client_key: str,
                instrument: contract.BrokerInstrument,
                side: contract.Side,
                quantity: Decimal) -> contract.CommandOutcome:
            if not instrument.broker_id:
                raise BrokerAuthorityRefused(
                    "Alpaca submit requires the durable broker asset_id; "
                    "ticker-only mutation is not certified")
            # Alpaca's create-order `symbol` parameter accepts an asset ID. Use
            # that stable handle directly so a symbol remap cannot retarget the
            # mutation between the final identity read and POST.
            body = {
                "symbol": str(instrument.broker_id),
                "qty": str(quantity),
                "side": "buy" if side is contract.Side.BUY else "sell",
                "type": "market",
                "time_in_force": "day",
                "client_order_id": client_key,
                "order_class": "simple",
                "extended_hours": False,
            }
            try:
                async with self._httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/v2/orders",
                        headers=self._headers(), json=body)
            except Exception as exc:                          # noqa: BLE001
                return contract.CommandOutcome(
                    state=CommandState.UNKNOWN,
                    detail=f"{type(exc).__name__}: {exc}")

            if resp.status_code in (200, 201):
                try:
                    payload = resp.json()
                except Exception as exc:                      # noqa: BLE001
                    return contract.CommandOutcome(
                        state=CommandState.UNKNOWN,
                        detail=("2xx response body unreadable: "
                                f"{type(exc).__name__}: {exc}"))
                try:
                    order = self._validate_submit_response(
                        payload, client_key=client_key,
                        instrument=instrument, side=side, quantity=quantity)
                except alpaca.IncompleteBrokerPayload as exc:
                    broker_order_id = (
                        str(payload.get("id") or "")
                        if isinstance(payload, dict) else "")
                    return contract.CommandOutcome(
                        state=CommandState.UNKNOWN,
                        broker_order_id=broker_order_id or None,
                        detail=f"incomplete 2xx acknowledgement: {exc}")
                return contract.CommandOutcome(
                    state=CommandState.ACKNOWLEDGED,
                    broker_order_id=order.broker_order_id,
                    detail="accepted by durable asset_id; lifecycle reconciles separately")
            if resp.status_code in (401, 403):
                raise alpaca.AlpacaCredentialsRefused(
                    f"Alpaca submit authority refused with HTTP "
                    f"{resp.status_code}: {(resp.text or '')[:500]}")
            if resp.status_code == 429:
                retry_after = alpaca._retry_after_seconds(resp)
                return alpaca.RetryableCommandOutcome(
                    state=CommandState.UNKNOWN,
                    retry_after_seconds=retry_after,
                    detail=("HTTP 429 rate limit; same-key retry eligible after "
                            f"{retry_after}s"))
            if resp.status_code == 408:
                return contract.CommandOutcome(
                    state=CommandState.UNKNOWN,
                    detail="HTTP 408 transport ambiguity")
            if resp.status_code == 422:
                text = (resp.text or "")[:500]
                if "client_order_id" in text or "duplicate" in text.lower():
                    return contract.CommandOutcome(
                        state=CommandState.UNKNOWN,
                        detail=f"duplicate key at broker: {text}")
                return contract.CommandOutcome(
                    state=CommandState.REJECTED, detail=text)
            if 400 <= resp.status_code < 500:
                return contract.CommandOutcome(
                    state=CommandState.REJECTED,
                    detail=(f"HTTP {resp.status_code}: "
                            f"{(resp.text or '')[:500]}"))
            return contract.CommandOutcome(
                state=CommandState.UNKNOWN,
                detail=f"HTTP {resp.status_code}")

        async def _bounded_activity_events(
                self, *, after: datetime,
                through: datetime,
                since_event_id: Optional[str] = None) -> tuple[dict, ...]:
            floor = alpaca._required_aware_ts(
                after, where="Activity SSE lower boundary")
            upper = alpaca._required_aware_ts(
                through, where="Activity SSE upper boundary")
            if floor > upper:
                raise alpaca.MalformedBrokerPayload(
                    "Activity SSE lower boundary exceeds upper boundary")
            if floor < _ACTIVITY_SSE_AVAILABLE_FROM:
                raise alpaca.MalformedBrokerPayload(
                    "Activity SSE history begins 2026-02-11; the requested "
                    "financial-history boundary predates the certified stream")

            account = await self.identify_account()
            account_uuid = str(account.raw.get("id") or "").strip()
            if not account_uuid:
                raise alpaca.MalformedBrokerPayload(
                    "Alpaca account payload has no UUID for Activity SSE binding")
            headers = dict(self._headers())
            headers["Accept"] = "text/event-stream"

            async def request(params: Mapping[str, str]) -> tuple[dict, ...]:
                try:
                    async with self._httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.get(
                            f"{self.base_url}/v2beta1/events/activities",
                            headers=headers, params=dict(params))
                except Exception as exc:                      # noqa: BLE001
                    raise RuntimeError(
                        "Activity SSE transport failed: "
                        f"{type(exc).__name__}: {exc}") from exc
                if resp.status_code in (401, 403):
                    raise alpaca.AlpacaCredentialsRefused(
                        "Activity SSE authority refused with HTTP "
                        f"{resp.status_code}")
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Activity SSE returned HTTP {resp.status_code}")
                events = tuple(_sse_events(
                    resp.text, malformed=alpaca.MalformedBrokerPayload))
                seen_event: set[str] = set()
                seen_ref: set[str] = set()
                prior_event = ""
                for event in events:
                    event_id = str(event.get("event_id") or "").strip()
                    ref_id = str(event.get("ref_id") or "").strip()
                    event_account = str(event.get("account_id") or "").strip()
                    if not event_id or not ref_id:
                        raise alpaca.MalformedBrokerPayload(
                            "Activity SSE event omitted event_id/ref_id")
                    if event_account != account_uuid:
                        raise alpaca.MalformedBrokerPayload(
                            "Activity SSE event belongs to another account")
                    if event_id in seen_event:
                        raise alpaca.MalformedBrokerPayload(
                            f"Activity SSE repeated event_id {event_id}")
                    if ref_id in seen_ref:
                        raise alpaca.MalformedBrokerPayload(
                            f"Activity SSE repeated ref_id {ref_id}")
                    if prior_event and event_id <= prior_event:
                        raise alpaca.MalformedBrokerPayload(
                            "Activity SSE event_id order is not strictly monotonic")
                    seen_event.add(event_id)
                    seen_ref.add(ref_id)
                    prior_event = event_id
                    if not isinstance(event.get("details"), dict):
                        raise alpaca.MalformedBrokerPayload(
                            f"Activity SSE event {event_id} has no details object")
                return events

            # Timestamp filters establish only a *bounded snapshot*. They are
            # not a replay cursor because Alpaca filters business time (`at`),
            # while delayed/backfilled events append later in event_id order.
            snapshot = await request({
                "since": floor.isoformat(), "until": upper.isoformat()})
            if since_event_id is None:
                return snapshot
            cursor = str(since_event_id).strip()
            if not cursor:
                raise alpaca.MalformedBrokerPayload(
                    "Activity SSE since_event_id must be non-empty")
            if not snapshot:
                # With no event in the complete owned-account interval there
                # is no newer upper cursor to replay through.
                return ()
            upper_event_id = str(snapshot[-1]["event_id"])
            if upper_event_id < cursor:
                raise alpaca.MalformedBrokerPayload(
                    "Activity SSE bounded upper event_id regressed")
            if upper_event_id == cursor:
                return ()

            replay = await request({
                "since_id": cursor, "until_id": upper_event_id})
            if not replay or str(replay[-1]["event_id"]) != upper_event_id:
                raise alpaca.MalformedBrokerPayload(
                    "Activity SSE cursor replay did not reach its bounded upper id")
            if str(replay[0]["event_id"]) < cursor:
                raise alpaca.MalformedBrokerPayload(
                    "Activity SSE cursor replay crossed behind its durable id")
            return replay

        async def account_cash_activities(
                self, *, after: datetime,
                through: datetime,
                since_event_id: Optional[str] = None
                ) -> broker_cash.BrokerCashActivityBatch:
            upper = alpaca._required_aware_ts(
                through, where="cash activity upper boundary")
            events = await self._bounded_activity_events(
                after=after, through=through,
                since_event_id=since_event_id)
            activities: list[broker_cash.BrokerCashActivity] = []
            last_ref: Optional[str] = None
            for event in events:
                previous_id = str(event.get("previous_id") or "").strip()
                details = event["details"]
                execution_type = str(details.get("execution_type") or "").lower()
                if previous_id or execution_type in {"trade_correct", "trade_bust"}:
                    # Correction/bust arithmetic must reverse the prior ref_id.
                    # Until that reversal is represented in the durable ledger,
                    # treating the new event as another positive fill is unsafe.
                    raise ActivityCorrectionRequiresRecovery(
                        "Activity SSE reported a correction/bust; cash/fill "
                        "authority is fenced until the prior ref_id is reversed")
                raw_amount = event.get("net_amount")
                if raw_amount is None:
                    continue
                amount = alpaca._required_dec(
                    raw_amount,
                    where=f"Activity SSE {event.get('event_id')} net_amount",
                    allow_negative=True)
                if amount == 0:
                    continue
                activity_type = str(event.get("activity_type") or "").upper()
                if activity_type not in broker_cash.RECOGNIZED_ACTIVITY_TYPES:
                    raise alpaca.MalformedBrokerPayload(
                        "unrecognized Activity SSE cash type "
                        f"{activity_type!r} with net_amount={amount}")
                settle = str(event.get("settle_date") or "")[:10]
                try:
                    activity_date = date.fromisoformat(settle)
                except ValueError:
                    executed = alpaca._required_aware_ts(
                        event.get("executed_at"),
                        where=f"Activity SSE {event.get('event_id')} executed_at")
                    activity_date = executed.date()
                ref_id = str(event["ref_id"])
                activities.append(broker_cash.BrokerCashActivity(
                    activity_id=ref_id,
                    activity_type=activity_type,
                    activity_date=activity_date,
                    net_amount=amount,
                    raw=event,
                ))
                last_ref = ref_id
            return broker_cash.BrokerCashActivityBatch(
                activities=tuple(activities),
                processed_through=upper,
                completeness=contract.Completeness.COMPLETE,
                last_activity_id=last_ref,
                last_event_id=(str(events[-1]["event_id"])
                               if events else since_event_id),
            )

        async def _recent_fills_bounded(
                self, since: datetime,
                through: Optional[datetime]) -> Sequence[contract.BrokerFill]:
            upper = through or datetime.now(timezone.utc)
            requested_floor = alpaca._required_aware_ts(
                since, where="fill activity lower boundary")
            if requested_floor > upper:
                raise alpaca.MalformedBrokerPayload(
                    "fill activity lower boundary exceeds upper boundary")
            # Terminal recovery cannot resume fill publication by business
            # timestamp: a fill may be backfilled after the durable terminal
            # watermark with an older ``at``/``executed_at``. Until fill
            # recovery owns its own durable event_id cursor, a bounded recovery
            # read deliberately traverses the complete Activity-SSE lifetime.
            # The unbounded diagnostic method retains its caller's time filter.
            event_floor = (
                _ACTIVITY_SSE_AVAILABLE_FROM
                if through is not None else requested_floor)
            events = await self._bounded_activity_events(
                after=event_floor, through=upper)
            fills: list[contract.BrokerFill] = []
            for event in events:
                if str(event.get("activity_type") or "").upper() != "TRD":
                    continue
                details = event["details"]
                execution_type = str(details.get("execution_type") or "fill").lower()
                if (event.get("previous_id")
                        or execution_type in {"trade_correct", "trade_bust"}):
                    raise ActivityCorrectionRequiresRecovery(
                        "trade correction/bust cannot be flattened into an "
                        "append-only fill history")
                order_id = str(details.get("order_id") or "").strip()
                if not order_id:
                    raise alpaca.MalformedBrokerPayload(
                        "TRD Activity SSE event omitted details.order_id")
                fills.append(NativeBrokerFill(
                    activity_id=str(event["ref_id"]),
                    client_key=(str(details.get("client_order_id"))
                                if details.get("client_order_id") else None),
                    broker_order_id=order_id,
                    quantity=alpaca._required_dec(
                        event.get("qty"),
                        where=f"TRD {event.get('event_id')} qty"),
                    price=alpaca._required_dec(
                        event.get("price"),
                        where=f"TRD {event.get('event_id')} price"),
                    filled_at=alpaca._required_aware_ts(
                        event.get("executed_at"),
                        where=f"TRD {event.get('event_id')} executed_at"),
                ))
            return tuple(fills)

        async def recent_fills(
                self, since: datetime) -> Sequence[contract.BrokerFill]:
            # Method remains available for diagnostics/reconciliation, but the
            # capability flag is intentionally false because a correction/bust
            # produces an explicit refusal rather than a lossy accounting row.
            return await self._recent_fills_bounded(
                since, datetime.now(timezone.utc))

    alpaca.AlpacaExecutionBroker = FinancialGradeAlpacaExecutionBroker

    # ------------------------------------------------------------------
    # Durable command identity: broker asset_id is economics, not decoration.
    # ------------------------------------------------------------------
    original_save_command = journal.save_command

    def save_command_with_asset_identity(conn, command, *args, **kwargs):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT broker_instrument_id FROM sentinel_commands"
                " WHERE client_key=%s",
                (command.client_key,),
            )
            row = cur.fetchone()
        if row is not None:
            stored = None if row[0] is None else str(row[0])
            incoming = (None if command.instrument.broker_id is None
                        else str(command.instrument.broker_id))
            if stored != incoming:
                raise journal.CommandEconomicsChanged(
                    f"{command.client_key} changed immutable broker_instrument_id "
                    f"from {stored!r} to {incoming!r}")
        return original_save_command(conn, command, *args, **kwargs)

    journal.save_command = save_command_with_asset_identity

    # ------------------------------------------------------------------
    # Retain account + asset provenance beside the legacy observation row.
    # ------------------------------------------------------------------
    original_record_observation = journal.record_observation

    def provenance_name(seq: int) -> str:
        return f"{_OBSERVATION_PREFIX}{int(seq)}"

    def record_observation_with_provenance(
            conn, observation, runtime_state: str = "") -> int:
        seq = original_record_observation(conn, observation, runtime_state)
        account = getattr(observation, "account_identity", None)
        if account is None:
            return seq
        payload = {
            "kind": "broker-observation/v2",
            "observation_seq": int(seq),
            "broker": str(account.broker),
            "account_id": str(account.account_id),
            "observed_at": observation.observed_at.astimezone(
                timezone.utc).isoformat(),
            "terminal_recovery_through": (
                observation.terminal_recovery_through.astimezone(
                    timezone.utc).isoformat()
                if observation.terminal_recovery_through is not None else None),
            "completeness": observation.completeness.value,
            "positions": [
                {"security_id": p.instrument.security_id,
                 "symbol": p.instrument.symbol,
                 "broker_id": p.instrument.broker_id,
                 "quantity": str(p.quantity)}
                for p in observation.positions
            ],
            "orders": [
                {"broker_order_id": o.broker_order_id,
                 "client_key": o.client_key,
                 "security_id": o.instrument.security_id,
                 "symbol": o.instrument.symbol,
                 "broker_id": o.instrument.broker_id,
                 "side": o.side.value,
                 "state": o.state.value,
                 "quantity": str(o.quantity),
                 "filled_quantity": str(o.filled_quantity),
                 "filled_average_price": (
                     str(o.filled_average_price)
                     if o.filled_average_price is not None else None)}
                for o in observation.orders
            ],
        }
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO NOTHING",
                (provenance_name(seq),
                 observation.observed_at.date().isoformat(),
                 json.dumps(payload, sort_keys=True)),
            )
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"broker observation provenance {seq} already exists; "
                    "observation identities must be append-only")
        conn.commit()
        return seq

    journal.record_observation = record_observation_with_provenance

    def load_provenance(conn, seq: int) -> dict:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s",
                (provenance_name(seq),),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"broker observation {seq} has no account/asset provenance")
        state = _loads_state(row[0], where=f"broker observation {seq} provenance")
        if (state.get("kind") != "broker-observation/v2"
                or state.get("observation_seq") != int(seq)):
            raise RuntimeError(
                f"broker observation {seq} provenance shape is invalid")
        return state

    # ------------------------------------------------------------------
    # Recovery watermark: a timestamp is never self-authenticating evidence.
    # ------------------------------------------------------------------
    def witness_name(broker_name: str, account_id: str) -> str:
        return f"{_WITNESS_PREFIX}{broker_name}:{account_id}"

    def observation_completion_proof(conn, through: datetime):
        through = journal._aware_utc(through, "terminal recovery witness")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT seq,observed_at,terminal_recovery_through,completeness,"
                " positions,orders FROM sentinel_observations"
                " WHERE terminal_recovery_through=%s AND completeness='COMPLETE'"
                " ORDER BY seq DESC",
                (through,),
            )
            candidates = cur.fetchall()
        broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
        for row in candidates:
            seq = int(row[0])
            try:
                provenance = load_provenance(conn, seq)
            except RuntimeError:
                continue
            if (provenance.get("broker") != broker_name
                    or provenance.get("account_id") != account_id
                    or provenance.get("terminal_recovery_through")
                    != through.isoformat()
                    or provenance.get("completeness") != "COMPLETE"):
                continue

            durable_rows = []
            complete = True
            for order in provenance.get("orders", []):
                key = order.get("client_key")
                if not is_sentinel_key(key):
                    continue
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT security_id,symbol,broker_instrument_id,side,"
                        " quantity,state,broker_order_id,filled_quantity,"
                        " filled_average_price FROM sentinel_commands"
                        " WHERE client_key=%s",
                        (key,),
                    )
                    command = cur.fetchone()
                if command is None:
                    complete = False
                    break
                expected = {
                    "security_id": str(command[0]),
                    "symbol": str(command[1]),
                    "broker_id": None if command[2] is None else str(command[2]),
                    "side": str(command[3]),
                    "quantity": str(command[4]),
                    "broker_order_id": (
                        None if command[6] is None else str(command[6])),
                }
                observed = {
                    "security_id": str(order.get("security_id")),
                    "symbol": str(order.get("symbol")),
                    "broker_id": order.get("broker_id"),
                    "side": str(order.get("side")),
                    "quantity": str(order.get("quantity")),
                    "broker_order_id": str(order.get("broker_order_id")),
                }
                if expected != observed:
                    complete = False
                    break
                # A broker fill cannot be ahead of the durable command at the
                # instant the recovery boundary is earned.
                if Decimal(str(command[7])) < Decimal(
                        str(order.get("filled_quantity") or "0")):
                    complete = False
                    break
                durable_rows.append({
                    "client_key": key,
                    "security_id": expected["security_id"],
                    "broker_id": expected["broker_id"],
                    "broker_order_id": expected["broker_order_id"],
                    "state": str(command[5]),
                    "filled_quantity": str(command[7]),
                    "filled_average_price": (
                        None if command[8] is None else str(command[8])),
                })
            if not complete:
                continue

            evidence = {
                "seq": seq,
                "observed_at": journal._aware_utc(
                    row[1], "broker observation").isoformat(),
                "processed_through": through.isoformat(),
                "provenance": provenance,
                "durable_commands": sorted(
                    durable_rows, key=lambda item: item["client_key"]),
            }
            digest = hashlib.sha256(json.dumps(
                evidence, sort_keys=True, separators=(",", ":"),
                default=str).encode("utf-8")).hexdigest()
            return seq, digest
        return None

    def strict_checkpoint(conn) -> datetime:
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
        processed = journal._aware_utc(
            row[2], "terminal recovery checkpoint")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s",
                (witness_name(broker_name, account_id),),
            )
            witness_row = cur.fetchone()
        if witness_row is None:
            # Upgrade or stale restore: the naked timestamp has not earned trust.
            # Replay from binding establishment rather than letting mutable SQL
            # narrow broker history.
            return established_at
        state = _loads_state(
            witness_row[0], where="terminal recovery completion witness")
        proof = observation_completion_proof(conn, processed)
        if proof is None:
            raise RuntimeError(
                "terminal recovery witness has no completed broker observation")
        seq, digest = proof
        expected = {
            "kind": "terminal-recovery-witness/v2",
            "broker": broker_name,
            "account_id": account_id,
            "processed_through": processed.isoformat(),
            "observation_seq": seq,
            "completion_sha256": digest,
        }
        if state != expected:
            raise RuntimeError(
                "terminal recovery watermark/completion witness disagree")
        return processed

    def strict_floor(conn) -> datetime:
        return strict_checkpoint(conn) - journal.TERMINAL_RECOVERY_OVERLAP

    def strict_advance(conn, through: datetime) -> datetime:
        candidate = journal._aware_utc(
            through, "terminal recovery upper boundary")
        current = strict_checkpoint(conn)
        processed = max(current, candidate)
        broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
        proof = observation_completion_proof(conn, processed)
        if proof is None:
            raise RuntimeError(
                "terminal recovery cannot advance: every Sentinel order in "
                "the exact COMPLETE observation is not yet durably reconciled")
        seq, digest = proof
        state = {
            "kind": "terminal-recovery-witness/v2",
            "broker": broker_name,
            "account_id": account_id,
            "processed_through": processed.isoformat(),
            "observation_seq": seq,
            "completion_sha256": digest,
        }
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_terminal_recovery_watermark"
                " (id,broker,broker_account_id,processed_through)"
                " VALUES (1,%s,%s,%s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " broker=EXCLUDED.broker,broker_account_id=EXCLUDED.broker_account_id,"
                " processed_through=EXCLUDED.processed_through,updated_at=NOW()",
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

    journal.terminal_recovery_checkpoint = strict_checkpoint
    journal.terminal_recovery_floor = strict_floor
    journal.advance_terminal_recovery_watermark = strict_advance

    # ------------------------------------------------------------------
    # Restore-grade unknown-order fence, independent of Alpaca pagination.
    # ------------------------------------------------------------------
    def database_incarnation(conn, *, initialize: bool = True):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (pg_control_system()).system_identifier::text,"
                " (pg_control_checkpoint()).timeline_id")
            system_identifier, timeline_id = cur.fetchone()
            cur.execute(
                "SELECT takeover_epoch,updated_at,broker,broker_account_id"
                " FROM sentinel_account_binding WHERE id=1")
            binding_row = cur.fetchone()
        if binding_row is None:
            raise RuntimeError("database incarnation check has no account binding")
        current = {
            "kind": "broker-recovery-db-incarnation/v1",
            "system_identifier": str(system_identifier),
            "timeline_id": int(timeline_id),
            "takeover_epoch": int(binding_row[0]),
        }
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s",
                (_DB_INCARCERATION_CURSOR,),
            )
            row = cur.fetchone()
        if row is None:
            if not initialize:
                return None, current, binding_row
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sentinel_processed_sessions"
                    " (cursor_name,session,state) VALUES (%s,CURRENT_DATE,%s::jsonb)",
                    (_DB_INCARCERATION_CURSOR,
                     json.dumps(current, sort_keys=True)),
                )
            conn.commit()
            return current, current, binding_row
        prior = _loads_state(row[0], where="database incarnation cursor")
        expected_keys = {"kind", "system_identifier", "timeline_id", "takeover_epoch"}
        if (set(prior) != expected_keys
                or prior.get("kind") != "broker-recovery-db-incarnation/v1"):
            raise RuntimeError("database incarnation cursor has unknown shape")
        return prior, current, binding_row

    def restore_increase_fence_reason(conn, deployment, today: date) -> str:
        prior, current, binding_row = database_incarnation(conn)
        assert prior is not None
        bound_epoch = int(binding_row[0])
        updated_at = binding_row[1]
        if not isinstance(updated_at, datetime) or updated_at.tzinfo is None:
            return "durable account binding has no trustworthy takeover timestamp"
        if (str(binding_row[2]) != deployment.broker
                or str(binding_row[3]) != deployment.broker_account_id
                or bound_epoch != deployment.takeover_epoch):
            return "execution deployment does not match the durable account binding"

        changed = (
            prior["system_identifier"] != current["system_identifier"]
            or int(prior["timeline_id"]) != int(current["timeline_id"])
        )
        if changed:
            if bound_epoch <= int(prior["takeover_epoch"]):
                return (
                    "PostgreSQL incarnation/timeline changed since the last "
                    "broker-recovery anchor. An explicit adopt-restored-account "
                    "takeover is required before any exposure increase")
            # The operator acknowledged this new physical DB incarnation by
            # advancing the takeover epoch. Bind the new anchor to that epoch.
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sentinel_processed_sessions SET session=CURRENT_DATE,"
                    " state=%s::jsonb,updated_at=NOW() WHERE cursor_name=%s",
                    (json.dumps(current, sort_keys=True),
                     _DB_INCARCERATION_CURSOR),
                )
            conn.commit()

        # The predecessor can still have an omitted working order after an
        # acknowledged takeover. Sentinel submits DAY orders only. Refuse BUYs
        # through the adoption calendar date; the next XNYS session is therefore
        # after every predecessor DAY order's contractual expiry boundary.
        if bound_epoch > 1 and today <= updated_at.date():
            return (
                "restored-account takeover occurred on "
                f"{updated_at.date().isoformat()}; exposure increases wait "
                "until a later session so predecessor DAY orders cannot remain "
                "executable even if Alpaca open-order enumeration omitted one")
        return ""

    def execution_restore_reason(*, conn, deployment, today):
        if deployment.broker != "alpaca":
            return ""
        return restore_increase_fence_reason(conn, deployment, today)

    executor.register_increase_fence_reason(execution_restore_reason)
    alpaca.restore_increase_fence_reason = restore_increase_fence_reason
    alpaca.database_incarnation = database_incarnation
    alpaca.ActivityCorrectionRequiresRecovery = ActivityCorrectionRequiresRecovery
    alpaca.RestoreGradeIncreaseDeferred = RestoreGradeIncreaseDeferred
    alpaca._FINAL_BOUNDARY_REMEDIATION_INSTALLED = True
    _INSTALLED = True


__all__ = [
    "ActivityCorrectionRequiresRecovery", "RestoreGradeIncreaseDeferred",
    "install",
]
