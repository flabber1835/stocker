"""Append-only revision accounting for qualified Alpaca cash activities."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from uuid import UUID

from sentinel.execution import broker_cash
from sentinel.execution.numeric import exact_decimal


PREFIX = "broker-cash-revision:v1:"
FULL_REPLACEMENT = "ALPACA_CASH_FULL_REPLACEMENT_V1"
_PUBLICATION_ID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
_CASH_TYPES = frozenset({"CSD", "CSW", "ACATC", "JNLC", "DIV", "FEE", "INT"})
_RELATION_FIELDS = frozenset({
    "asset_id", "ca_id", "group_id", "cusip", "external_id", "journal_id",
    "order_id", "parent_id", "request_id", "symbol",
})


class CashRevisionRefused(broker_cash.BrokerCashAuthorityRefused):
    pass


@dataclass(frozen=True)
class NativePosting:
    reference: str
    event_id: str
    predecessor: str | None
    activity_type: str
    subtype: str | None
    settlement_day: date
    amount: Decimal
    relationship: str
    wire: str


@dataclass(frozen=True)
class CashRevision:
    before: NativePosting
    after: NativePosting


@dataclass(frozen=True)
class LedgerDifference:
    reference: str
    flow_id: str
    session: date
    amount: Decimal
    detail: str

    @property
    def member_commitment(self) -> str:
        return broker_cash._member_commitment(self.flow_id, self.session, self.amount, self.detail)


@dataclass(frozen=True)
class StageResult:
    differences: tuple[LedgerDifference, ...]
    accepted: int
    commitment: str | None


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("cash revision requires a canonical native reference")
    return value


def _native_amount(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("native cash amount must be a bounded decimal string")
    number = Decimal(value)
    if (not number.is_finite() or abs(number.adjusted()) > 30
            or abs(number.as_tuple().exponent) > 30):
        raise ValueError("native cash amount exceeds the exact decimal domain")
    return number


def _date(raw):
    if isinstance(raw, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return date.fromisoformat(raw)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.utcoffset() == timezone.utc.utcoffset(parsed) and parsed.time().isoformat() == "00:00:00":
            return parsed.date()
    raise ValueError("cash revision has no exact settlement day")


def _wire(value) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _posting(event, native_account_uuid):
    try:
        account_uuid = _uuid(native_account_uuid)
        if "account_id" in event and event["account_id"] != account_uuid:
            raise ValueError("cash revision changed the authenticated account")
        kind = event["activity_type"]
        subtype = event.get("activity_subtype")
        if (kind not in _CASH_TYPES or event["currency"] != "USD" or event["status"] != "executed"
                or subtype is not None and (not isinstance(subtype, str) or not subtype.strip())
                or kind == "DIV" and subtype != "CDIV"):
            raise ValueError("activity is outside the supported cash-only contract")
        raw_quantity = event.get("qty")
        if kind != "DIV" and raw_quantity is not None and _native_amount(raw_quantity) != 0:
            raise ValueError("ordinary cash-only revision cannot modify share quantity")
        amount = _native_amount(event["net_amount"])
        if (kind == "CSD" and amount < 0) or (kind == "CSW" and amount > 0):
            raise ValueError("cash deposit/withdrawal sign contradicts the native type")
        reference = _uuid(event["ref_id"])
        predecessor = event.get("previous_id")
        if predecessor is not None and _uuid(predecessor) == reference:
            raise ValueError("cash revision references itself")
        event_id = event["event_id"]
        if not isinstance(event_id, str) or not _PUBLICATION_ID.fullmatch(event_id):
            raise ValueError("cash revision requires a publication ULID")
        details = event["details"]
        if not isinstance(details, dict) or details.get("execution_type") is not None:
            raise ValueError("cash revision has no native relationship object")
        related = {k: details[k] for k in _RELATION_FIELDS if k in details}
        if any(not isinstance(value, str) or not value for value in related.values()):
            raise ValueError("cash revision has malformed native relationship fields")
        if event.get("asset") is not None:
            related["asset_id_envelope"] = _uuid(event["asset"]["id"])
            if "asset_id" in related and related["asset_id"] != related["asset_id_envelope"]:
                raise ValueError("cash revision has contradictory native asset identity")
        return NativePosting(reference, event_id, predecessor, kind, subtype,
                             _date(event["settle_date"]), amount, _wire(related), _wire(event))
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise CashRevisionRefused(f"invalid Alpaca cash revision evidence: {exc}") from exc


def decode(before, after, *, native_account_uuid: str) -> CashRevision:
    """Revalidate the exact native predecessor and replacement as a pair."""
    prior, revision = (_posting(event, native_account_uuid) for event in (before, after))
    if (revision.predecessor != prior.reference or revision.event_id <= prior.event_id
            or (revision.activity_type, revision.subtype, revision.settlement_day, revision.relationship)
            != (prior.activity_type, prior.subtype, prior.settlement_day, prior.relationship)):
        raise CashRevisionRefused("cash revision changed lineage, kind, settlement day or native relation")
    return CashRevision(prior, revision)


def is_revision_candidate(event):
    return (bool(event.get("previous_id")) and event.get("activity_type") in _CASH_TYPES
            and (event["activity_type"] != "DIV" or event.get("activity_subtype") == "CDIV"))


def _namespace(broker, account_id):
    return PREFIX + broker_cash._digest([broker, account_id]) + ":"


def _record(revision, *, native_account_uuid):
    return {"schema": PREFIX.removesuffix(":"), "account_uuid": native_account_uuid,
            "before": json.loads(revision.before.wire), "after": json.loads(revision.after.wire)}


def _row(conn, name):
    return conn.execute(
        "SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (name,)).fetchone()


def _rows(conn, namespace):
    return conn.execute(
        "SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name LIKE %s ORDER BY cursor_name",
        (namespace + "%",)).fetchall()


def _commitment(rows):
    return broker_cash._digest(rows) if rows else None


def _flow(conn, flow_id):
    return conn.execute(
        "SELECT session,amount,detail FROM sentinel_cash_flows WHERE flow_id=%s", (flow_id,)).fetchone()


def _zero(conn, *, broker, account_id, ref):
    return conn.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s",
                        (f"broker-cash-zero:v1:{broker}:{account_id}:{ref}",)).fetchone()


def _difference(revision, *, broker, account_id):
    prior, replacement = revision.before, revision.after
    kind = "EXTERNAL" if prior.activity_type in broker_cash.EXTERNAL_ACTIVITY_TYPES else "INTERNAL"
    detail = f"{broker_cash.DETAIL_PREFIX}class={kind};type=CORR;id={replacement.reference}"
    return LedgerDifference(replacement.reference,
        broker_cash.broker_flow_id(broker=broker, account_id=account_id, activity_id=replacement.reference),
        prior.settlement_day, exact_decimal(Fraction(replacement.amount) - Fraction(prior.amount)), detail)


def replayed_flow_ids(revisions, *, broker, account_id):
    effects = (_difference(revision, broker=broker, account_id=account_id) for revision in revisions)
    return {effect.flow_id for effect in effects if effect.amount}


def commitment(conn, *, broker, account_id):
    return _commitment(_rows(conn, _namespace(broker, account_id)))


def retained_differences(conn, references, *, broker, account_id):
    """Validate CORR cash rows with one bounded receipt lookup."""
    namespace = _namespace(broker, account_id) + "native:"
    expected = {namespace + ref for ref in references}
    rows = conn.execute("SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name=ANY(%s)",
                        (sorted(expected),)).fetchall()
    if {key for key, _ in rows} != expected:
        raise CashRevisionRefused("cash ledger contains an unproved revision difference")
    differences = {}
    for key, receipt in rows:
        revision = decode(receipt["before"], receipt["after"], native_account_uuid=receipt["account_uuid"])
        difference = _difference(revision, broker=broker, account_id=account_id)
        if key != namespace + difference.reference or not difference.amount:
            raise CashRevisionRefused("cash ledger revision difference has inconsistent identity")
        differences[difference.flow_id] = difference
    return differences


def _prove_predecessor(conn, namespace, prior, *, broker, account_id):
    if prior.predecessor is not None:
        stored = _row(conn, namespace + "native:" + prior.reference)
        if stored is None or stored[0].get("after") != json.loads(prior.wire):
            raise CashRevisionRefused("cash revision lacks its retained full predecessor contribution")
        return
    native = broker_cash.BrokerCashActivity(prior.reference, prior.activity_type,
                                            prior.settlement_day, prior.amount, json.loads(prior.wire))
    flow_id = broker_cash.broker_flow_id(broker=broker, account_id=account_id, activity_id=prior.reference)
    retained = _flow(conn, flow_id)
    zero = _zero(conn, broker=broker, account_id=account_id, ref=prior.reference)
    detail = broker_cash._detail(native)
    if prior.amount == 0:
        valid = retained is None and zero == (prior.settlement_day, {"kind": "broker-cash-zero/v1", "detail": detail})
    else:
        valid = zero is None and retained == (prior.settlement_day, prior.amount, detail)
    if not valid:
        raise CashRevisionRefused("cash revision predecessor differs from the retained ordinary cash posting")


def _verify_difference(conn, difference, *, broker, account_id):
    expected = ((difference.session, difference.amount, difference.detail) if difference.amount else None)
    if (_flow(conn, difference.flow_id) != expected
            or _zero(conn, broker=broker, account_id=account_id, ref=difference.reference) is not None):
        raise CashRevisionRefused("retained cash revision has a missing or conflicting cash difference")


def stage(conn, revisions, *, broker, account_id, native_account_uuid,
          replacement_contract=None) -> StageResult:
    """Stage in the activity cursor owner's transaction, without committing."""
    from sentinel import binding

    if not revisions:
        return StageResult((), 0, None)
    if replacement_contract != FULL_REPLACEMENT or broker not in {"alpaca", "alpaca-live"}:
        raise CashRevisionRefused("cash amount replacement semantics are not qualified for this stream")
    if broker == "alpaca-live" and account_id != native_account_uuid:
        raise CashRevisionRefused("LIVE cash revision native account differs from its bound account")
    owner = binding.require(conn)
    if (owner.broker, owner.broker_account_id) != (broker, account_id) or not owner.is_owned:
        raise CashRevisionRefused("cash revision has no matching owned account")
    namespace = _namespace(broker, account_id)
    differences, accepted = [], 0
    last_event_id = ""
    receipts = [record for key, record in _rows(conn, namespace)
                if key.startswith(namespace + "native:")]
    if any(record["account_uuid"] != native_account_uuid for record in receipts):
        raise CashRevisionRefused("cash revision stream changed its retained native account")
    retained_head = max((record["after"]["event_id"] for record in receipts), default="")
    for revision in revisions:
        prior, replacement = revision.before, revision.after
        if (replacement.event_id <= last_event_id
                or revision != decode(json.loads(prior.wire), json.loads(replacement.wire),
                                      native_account_uuid=native_account_uuid)):
            raise CashRevisionRefused("cash revision batch contains reordered or changed evidence")
        last_event_id = replacement.event_id
        native_name = namespace + "native:" + replacement.reference
        consumed_name = namespace + "consumed:" + prior.reference
        record = _record(revision, native_account_uuid=native_account_uuid)
        consumed = {"successor": replacement.reference}
        stored, old = _row(conn, native_name), _row(conn, consumed_name)
        difference = _difference(revision, broker=broker, account_id=account_id)
        _prove_predecessor(conn, namespace, prior, broker=broker, account_id=account_id)
        if stored is not None:
            if stored != (record,) or old != (consumed,):
                raise CashRevisionRefused("native cash revision replay changed or lost its lineage")
            _verify_difference(conn, difference, broker=broker, account_id=account_id)
            continue
        if old is not None:
            raise CashRevisionRefused("native cash predecessor was already consumed")
        if replacement.event_id <= retained_head:
            raise CashRevisionRefused("new cash revision regressed the retained publication order")
        if (_flow(conn, difference.flow_id) is not None
                or _zero(conn, broker=broker, account_id=account_id, ref=difference.reference) is not None):
            raise CashRevisionRefused("native cash revision reused an existing posting reference")
        for key, payload in ((native_name, record), (consumed_name, consumed)):
            conn.execute("INSERT INTO sentinel_processed_sessions (cursor_name,session,state)"
                         " VALUES (%s,%s,%s::jsonb)", (key, difference.session, _wire(payload)))
        if difference.amount:
            conn.execute("INSERT INTO sentinel_cash_flows (flow_id,session,amount,detail) VALUES (%s,%s,%s,%s)",
                         (difference.flow_id, difference.session, difference.amount, difference.detail))
            differences.append(difference)
        accepted += 1
        retained_head = replacement.event_id
    return StageResult(tuple(differences), accepted, _commitment(_rows(conn, namespace)))


def verify_restored(conn, *, broker, account_id, expected_commitment):
    namespace = _namespace(broker, account_id)
    rows = _rows(conn, namespace)
    if _commitment(rows) != expected_commitment:
        raise CashRevisionRefused("cash revision receipts disagree with the restored activity cursor")
    records = dict(rows)
    expected = set()
    seen_events = set()
    accounts = set()
    for key, receipt in rows:
        if not key.startswith(namespace + "native:"):
            continue
        accounts.add(receipt["account_uuid"])
        revision = decode(receipt["before"], receipt["after"], native_account_uuid=receipt["account_uuid"])
        prior, replacement = revision.before, revision.after
        consumed = namespace + "consumed:" + prior.reference
        if (key != namespace + "native:" + replacement.reference
                or receipt != _record(revision, native_account_uuid=receipt["account_uuid"])
                or records.get(consumed) != {"successor": replacement.reference}
                or replacement.event_id in seen_events):
            raise CashRevisionRefused("restored cash revision lineage is inconsistent")
        expected.update((key, consumed))
        seen_events.add(replacement.event_id)
        _prove_predecessor(conn, namespace, prior, broker=broker, account_id=account_id)
        _verify_difference(conn, _difference(revision, broker=broker, account_id=account_id),
                           broker=broker, account_id=account_id)
    if set(records) != expected or len(accounts) > 1:
        raise CashRevisionRefused("restored cash revision references span divergent lineages")
    if broker == "alpaca-live" and accounts and accounts != {account_id}:
        raise CashRevisionRefused("restored LIVE revisions changed their bound native account")
