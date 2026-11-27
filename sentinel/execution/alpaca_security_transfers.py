"""Durable evidence for independently matched, restricted in-kind transfers."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import re
from uuid import UUID

from sentinel.execution.states import IN_FLIGHT


KINDS = frozenset({"ACATS", "FOPT", "JNLS"})
PREFIX = "alpaca-in-kind-event:v1:"
SCHEMA = "sentinel.alpaca-in-kind-event/1"
_EVENT_ID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")
_QUANTITY = re.compile(r"-?[0-9]{1,24}(?:\.[0-9]{1,12})?")


class SecurityTransferRefused(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _uuid(value):
    try:
        if isinstance(value, str) and str(UUID(value)) == value and UUID(value).int:
            return value
    except ValueError:
        pass
    return None


def _prefix(broker, account_id):
    return PREFIX + _digest([broker, account_id]) + ":"


def validate_event(raw, *, native_account):
    """Accept an executed zero-cash posting without inventing missing identity."""
    from sentinel.execution.alpaca import _activity_settle_date, _required_aware_ts

    try:
        qty, cash = raw["qty"], raw["net_amount"]
        if (raw["activity_type"] not in KINDS or raw["status"] != "executed"
                or raw["currency"] != "USD" or raw.get("previous_id")
                or raw.get("account_id", native_account) != native_account
                or not _uuid(native_account) or not _uuid(raw["ref_id"])
                or not _EVENT_ID.fullmatch(raw["event_id"])
                or not _QUANTITY.fullmatch(qty) or not Decimal(qty)
                or not _QUANTITY.fullmatch(cash) or Decimal(cash)):
            raise ValueError("not an executed, zero-cash securities transfer")
        day = _activity_settle_date(raw["settle_date"])
        executed_at = _required_aware_ts(raw["executed_at"], where="securities transfer")
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise SecurityTransferRefused("Alpaca securities transfer lacks exact zero-cash evidence") from exc
    return day, executed_at, Fraction(Decimal(qty))


def _load(conn, *, broker, account_id, proof):
    prefix = _prefix(broker, account_id)
    rows = conn.execute("SELECT cursor_name,session,state FROM sentinel_processed_sessions"
                        " WHERE cursor_name LIKE %s ORDER BY cursor_name", (prefix + "%",)).fetchall()
    if proof is None:
        if rows:
            raise SecurityTransferRefused("in-kind evidence exists without its account cursor")
        return {}
    if (not isinstance(proof, dict) or set(proof) != {"native_account_id", "sha256"}
            or not _uuid(proof["native_account_id"])):
        raise SecurityTransferRefused("in-kind activity commitment is malformed")
    native = proof["native_account_id"]
    retained = {}
    for name, session, state in rows:
        ref = name.removeprefix(prefix)
        if (not isinstance(state, dict) or set(state) != {"schema", "subject", "raw"}
                or state["schema"] != SCHEMA or state["subject"] != [broker, account_id, native]
                or not isinstance(state["raw"], dict) or state["raw"].get("ref_id") != ref):
            raise SecurityTransferRefused("in-kind activity receipt changed identity")
        raw = state["raw"]
        day, _, _ = validate_event(raw, native_account=native)
        if day != session:
            raise SecurityTransferRefused("in-kind activity receipt changed settlement day")
        retained[ref] = raw
    if (proof["sha256"] != _digest(retained)
            or len({raw["event_id"] for raw in retained.values()}) != len(retained)):
        raise SecurityTransferRefused("in-kind activity receipts disagree with the replay cursor")
    return retained


def record(conn, *, broker, account_id, prior, native_account, events):
    """Write inside the transaction owned by the account activity cursor."""
    if (not isinstance(native_account, tuple) or len(native_account) != 3
            or native_account[:2] != (broker, account_id) or not _uuid(native_account[2])):
        raise SecurityTransferRefused("in-kind activity lacks the exact native account")
    native = native_account[2]
    retained = _load(conn, broker=broker, account_id=account_id, proof=prior)
    if prior is not None and prior["native_account_id"] != native:
        raise SecurityTransferRefused("in-kind activity native account changed")
    event_ids = {raw["event_id"] for raw in retained.values()}
    prefix = _prefix(broker, account_id)
    for raw in events:
        day, _, _ = validate_event(raw, native_account=native)
        ref = raw["ref_id"]
        if ref in retained:
            if _json(retained[ref]) != _json(raw):
                raise SecurityTransferRefused("in-kind activity changed under its native reference")
            continue
        if raw["event_id"] in event_ids:
            raise SecurityTransferRefused("in-kind activity repeats a publication identity")
        conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state)"
                     " VALUES (%s,%s,%s::jsonb)", (prefix + ref, day, _json({
                         "schema": SCHEMA, "subject": list(native_account), "raw": raw})))
        event_ids.add(raw["event_id"])
        retained[ref] = raw
    return {"native_account_id": native, "sha256": _digest(retained)}


def verify_restored(conn, *, state):
    prefix = _prefix(state.broker, state.account_id) + "%" if state else ""
    if conn.execute("SELECT EXISTS(SELECT 1 FROM sentinel_processed_sessions"
                    " WHERE cursor_name LIKE %s AND cursor_name NOT LIKE %s)",
                    (PREFIX + "%", prefix)).fetchone()[0]:
        raise SecurityTransferRefused("restored in-kind evidence has no bound account cursor")
    if state is not None:
        _load(conn, broker=state.broker, account_id=state.account_id,
              proof=state.security_transfer_commitment)


@dataclass(frozen=True)
class Transfer:
    asset: str
    quantity: Fraction
    ownership_before: datetime


def explain(*, transfers, commands, expected, observation, eligible, actions, prior_fills):
    """Explain exact share movements and keep the relevant assets restricted."""
    scalar = getattr(actions, "scalar_evidence_for", None)
    material = getattr(actions, "material_events_for", None)
    if not callable(scalar) or not callable(material) or not observation.is_complete:
        return {}
    positions = observation.positions_by_security()
    instruments = [position.instrument for position in observation.positions]
    instruments.extend(command.instrument for command in commands)
    ids, aliases, symbols = defaultdict(set), defaultdict(set), defaultdict(set)
    for instrument in instruments:
        ids[instrument.broker_id].add(instrument.security_id)
        aliases[instrument.security_id].add(instrument.broker_id)
        symbols[instrument.security_id].add(instrument.symbol)
    by_asset = defaultdict(list)
    for entry in transfers:
        by_asset[entry.asset].append(entry)
    restrictions = {}
    for asset, entries in by_asset.items():
        if len(ids[asset]) != 1:
            continue
        sid, = ids[asset]
        if sid not in eligible or aliases[sid] != {asset}:
            continue
        first = min(entry.ownership_before for entry in entries)
        related = [command for command in commands if command.security_id == sid]
        if (any(order.is_working and (order.instrument.security_id == sid
                    or order.instrument.broker_id == asset) for order in observation.orders)
                or any(command.state in IN_FLIGHT or command.created_at is None
                       or command.created_at >= first for command in related)
                or any(event.session >= first.date() for event in (*scalar((sid,)),
                       *material(security_ids=(sid,), symbols=tuple(symbols[sid]))))
                or not prior_fills(related, first)):
            continue
        quantity = Fraction(expected.get(sid, 0))
        for entry in sorted(entries, key=lambda item: item.ownership_before):
            quantity += entry.quantity
            if quantity < 0:
                break
        else:
            if quantity == Fraction(positions.get(sid, 0)):
                restrictions[sid] = "SECURITIES_TRANSFER_RESTRICTED: confirmed in-kind shares"
    return restrictions


def reconciled_restrictions(conn, *, state, commands, expected, observation, eligible, actions):
    from sentinel.execution import journal
    from sentinel.execution.commands import is_legacy_migration

    identity = observation.account_identity
    proof = state.security_transfer_commitment if state is not None else None
    if (proof is None or identity is None or not eligible
            or (identity.broker, identity.account_id, identity.raw.get("id")) != (
                state.broker, state.account_id, proof["native_account_id"])
            or not (observation.observed_at - timedelta(seconds=60)
                    <= state.processed_through <= observation.observed_at)):
        return {}
    raw = _load(conn, broker=state.broker, account_id=state.account_id, proof=proof)
    transfers = []
    for item in raw.values():
        day, at, quantity = validate_event(item, native_account=proof["native_account_id"])
        asset_data = item.get("asset")
        asset = _uuid(asset_data.get("id")) if isinstance(asset_data, dict) else None
        if day > observation.observed_at.date() or at > observation.observed_at:
            continue
        if not asset:
            return {}
        # A same-day trade creates an ownership ordering the transfer alone cannot prove.
        cutoff = min(at, datetime.combine(day, time.min, tzinfo=timezone.utc))
        transfers.append(Transfer(asset, quantity, cutoff))

    def prior_fills(related, cutoff):
        if any(is_legacy_migration(command) for command in related):
            return False
        wanted = {command.client_key: Fraction(command.filled_quantity)
                  for command in related if command.filled_quantity}
        if not wanted:
            return True
        fills = conn.execute(f"SELECT client_key,quantity,filled_at FROM {journal.ACTIVE_FILLS} active"
                             " WHERE client_key=ANY(%s)", (sorted(wanted),)).fetchall()
        observed = defaultdict(Fraction)
        for key, quantity, at in fills:
            if at is None or at >= cutoff:
                return False
            observed[key] += Fraction(quantity)
        return observed == wanted

    return explain(transfers=transfers, commands=commands, expected=expected,
                   observation=observation, eligible=eligible, actions=actions,
                   prior_fills=prior_fills)
