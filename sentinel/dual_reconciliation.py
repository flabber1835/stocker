"""Authority bridge from certified shadow intent to PAPER transport.

The broker-free shadow ledger remains the performance authority. Alpaca PAPER
may transport the same strategy only after its immutable plan proves that it
names the exact current verified shadow state and allocation.

A causal-gap shadow segment is a new economic genesis, not merely a new chart
segment: Wealth Core/controller path state cannot be reconstructed truthfully
from missed prospective sessions. Such a segment may continue as a new research
observation automatically, but broker transport requires two independent facts:

* explicit operator approval bound to the exact append-only segment marker; and
* one durable broker handover proving the newly initialized strategy first met a
  COMPLETE, flat, clean account with no order or Sentinel command that could
  still move it.

Strategy economics and broker-currentness are deliberately separate. The plan's
immutable dual sizing authority remains frozen forever; the handover receipt
retains its SHA. Flatness is proved from the latest durable, finalized broker
reconciliation row and the receipt also binds that row's sequence/content hash.
A crash after plan adoption can therefore re-observe Alpaca and finish the
handover without rewriting the plan or pretending a later broker snapshot was
used for sizing.

Verification remains read-only by default. The production preparation callback
enters an async-safe preparation scope so its pre-plan shadow check can run before
the handover exists and its post-plan reconciliation may establish the receipt.
Inspection, recovery, convergence, and execution never enter that scope and must
observe an already-durable handover before a current post-gap plan can transport.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
from typing import Any, Mapping

from sentinel import dual_plan_authority, shadow_runtime, shadow_segments
from sentinel.execution import journal
from sentinel.execution.states import CommandState, IN_FLIGHT
from sentinel.feed import calendar


REGENESIS_APPROVAL_ENV = "SENTINEL_SHADOW_REGENESIS_APPROVAL_SHA256"
REGENESIS_HANDOVER_SCHEMA = "sentinel.dual-regenesis-broker-handover/2"
REGENESIS_HANDOVER_PREFIX = "dual-regenesis-broker-handover:v2:"
REGENESIS_OBSERVATION_SCHEMA = "sentinel.dual-regenesis-broker-observation/2"
REGENESIS_HANDOVER_MAX_AGE_SECONDS = 300
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REGENESIS_PREPARATION_SCOPE = ContextVar(
    "sentinel_dual_regenesis_preparation_scope", default=False)

# Dual reconciliation can run in automation, an authorized CLI, or tests. Every
# process must resolve the same active append-only segment as the shadow worker.
shadow_segments.install_runtime_store(shadow_runtime)


class DualReconciliationPending(RuntimeError):
    """The shadow service or explicit transport approval is not yet current."""


class DualReconciliationRefused(RuntimeError):
    """Shadow intent and PAPER transport authority do not match exactly."""


@contextmanager
def regenesis_preparation_scope():
    """Allow only this async/task context to run before a handover exists."""
    token = _REGENESIS_PREPARATION_SCOPE.set(True)
    try:
        yield
    finally:
        _REGENESIS_PREPARATION_SCOPE.reset(token)


def regenesis_preparation_active() -> bool:
    """Whether this task is the explicit production preparation transition."""
    return bool(_REGENESIS_PREPARATION_SCOPE.get())


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DualReconciliationRefused(
            "re-genesis handover evidence is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _decimal(value: Any, *, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DualReconciliationRefused(f"{label} is not a decimal") from exc
    if not parsed.is_finite():
        raise DualReconciliationRefused(f"{label} is not finite")
    return parsed


def _aware(value: Any, *, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise DualReconciliationRefused(f"{label} is not a timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        raise DualReconciliationRefused(f"{label} is timezone-naive")
    return value.astimezone(timezone.utc)


def _json_value(value: Any, *, label: str, expected_type):
    if isinstance(value, expected_type):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DualReconciliationRefused(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, expected_type):
        raise DualReconciliationRefused(f"{label} has an unexpected JSON type")
    return parsed


def _require_regenesis_transport_approval(conn, observation_id: str):
    """Return active segment; require exact marker approval after a causal gap."""
    try:
        segment = shadow_segments.active_segment(conn, observation_id)
    except shadow_segments.ShadowSegmentRefused as exc:
        raise DualReconciliationRefused(
            f"shadow performance segment authority is invalid: {exc}") from exc
    if segment.index == 0:
        return segment
    marker = str(segment.marker_sha256 or "")
    approved = str(os.environ.get(REGENESIS_APPROVAL_ENV, "")).strip()
    if approved != marker:
        raise DualReconciliationPending(
            "certified shadow restarted after a causal outage as economic "
            f"segment {segment.index}; broker transport remains fenced until "
            f"{REGENESIS_APPROVAL_ENV} equals the exact segment marker "
            f"{marker}")
    return segment


def _handover_cursor(observation_id: str, segment_index: int) -> str:
    logical = str(observation_id)
    if not logical or ":" in logical:
        raise DualReconciliationRefused(
            "shadow observation id is invalid for re-genesis handover")
    if isinstance(segment_index, bool) or int(segment_index) < 1:
        raise DualReconciliationRefused(
            "re-genesis handover requires a positive segment index")
    return f"{REGENESIS_HANDOVER_PREFIX}{logical}:{int(segment_index):08d}"


def _observation_evidence(conn, *, seq: int | None = None):
    """Return canonical durable broker evidence, its hash, and UTC observation time."""
    sql = (
        "SELECT o.seq,o.observed_at,o.terminal_recovery_through,"
        " o.completeness,o.positions,o.orders,o.runtime_state,"
        " p.broker,p.broker_account_id,p.observed_at,p.positions"
        " FROM sentinel_observations o"
        " LEFT JOIN sentinel_observation_provenance p"
        "   ON p.observation_seq=o.seq")
    params = ()
    if seq is None:
        sql += " ORDER BY o.seq DESC LIMIT 1"
    else:
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise DualReconciliationRefused(
                "re-genesis broker observation sequence is invalid")
        sql += " WHERE o.seq=%s"
        params = (seq,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if row is None:
        return None
    if len(row) != 11:
        raise DualReconciliationRefused(
            "durable broker observation query returned an unknown shape")
    (observation_seq, observed_at, terminal_through, completeness,
     raw_positions, raw_orders, runtime_state, broker, broker_account_id,
     provenance_observed_at, raw_provenance_positions) = row
    if (isinstance(observation_seq, bool) or not isinstance(observation_seq, int)
            or observation_seq < 1):
        raise DualReconciliationRefused(
            "durable broker observation sequence is invalid")
    observed = _aware(observed_at, label="durable broker observed_at")
    if terminal_through is not None:
        terminal = _aware(
            terminal_through, label="durable broker terminal recovery boundary")
    else:
        terminal = None
    provenance_observed = _aware(
        provenance_observed_at, label="broker observation provenance time")
    if provenance_observed != observed:
        raise DualReconciliationRefused(
            "broker observation provenance timestamp disagrees with observation")
    broker = str(broker or "").strip()
    broker_account_id = str(broker_account_id or "").strip()
    if not broker or not broker_account_id:
        raise DualReconciliationRefused(
            "durable broker observation lacks account provenance")
    positions = _json_value(
        raw_positions, label="durable broker positions", expected_type=dict)
    orders = _json_value(
        raw_orders, label="durable broker orders", expected_type=list)
    provenance_record = _json_value(
        raw_provenance_positions, label="broker observation provenance",
        expected_type=dict)
    if set(provenance_record) != {"started_at", "positions"}:
        raise DualReconciliationRefused(
            "broker observation provenance has an unknown shape")
    started_at = _aware(
        datetime.fromisoformat(str(provenance_record["started_at"])),
        label="durable broker observation start")
    provenance_positions = provenance_record["positions"]
    if not isinstance(provenance_positions, list):
        raise DualReconciliationRefused(
            "broker position provenance is not a list")
    valid_states = {state.value for state in CommandState}
    for index, order in enumerate(orders):
        if not isinstance(order, Mapping):
            raise DualReconciliationRefused(
                f"durable broker order {index} is malformed")
        expected = {
            "id", "key", "security_id", "symbol", "broker_instrument_id",
            "side", "state", "qty", "filled", "filled_average_price",
            "submitted_at", "external_replacement", "replaced_by", "replaces",
        }
        if set(order) != expected or str(order.get("state") or "") not in valid_states:
            raise DualReconciliationRefused(
                f"durable broker order {index} has an unknown shape/state")
        _decimal(order.get("qty"), label=f"durable broker order {index} quantity")
        _decimal(order.get("filled"), label=f"durable broker order {index} fill")
        if type(order.get("external_replacement")) is not bool:
            raise DualReconciliationRefused(
                f"durable broker order {index} replacement flag is malformed")
    for security_id, quantity in positions.items():
        if not str(security_id):
            raise DualReconciliationRefused(
                "durable broker positions contain an empty security id")
        _decimal(quantity, label=f"durable broker position {security_id}")
    for index, position in enumerate(provenance_positions):
        if not isinstance(position, Mapping) or set(position) != {
                "security_id", "symbol", "broker_instrument_id", "quantity"}:
            raise DualReconciliationRefused(
                f"durable broker position provenance {index} is malformed")
        if not str(position.get("security_id") or ""):
            raise DualReconciliationRefused(
                f"durable broker position provenance {index} lacks security id")
        _decimal(
            position.get("quantity"),
            label=f"durable broker position provenance {index} quantity")
    body = {
        "schema": REGENESIS_OBSERVATION_SCHEMA,
        "observation_seq": observation_seq,
        "started_at": started_at.isoformat(),
        "observed_at": observed.isoformat(),
        "terminal_recovery_through": (
            None if terminal is None else terminal.isoformat()),
        "completeness": str(completeness or ""),
        "positions": json.loads(_canonical(positions)),
        "orders": json.loads(_canonical(orders)),
        "runtime_state": str(runtime_state or ""),
        "broker": broker,
        "broker_account_id": broker_account_id,
        "provenance_positions": json.loads(_canonical(provenance_positions)),
    }
    return body, _sha256(body), observed


def _require_flat_observation_body(body: Mapping, *, binding=None) -> None:
    if body.get("schema") != REGENESIS_OBSERVATION_SCHEMA:
        raise DualReconciliationRefused(
            "re-genesis broker observation has an unknown schema")
    if body.get("completeness") != "COMPLETE" or body.get("runtime_state") != "RUNNING":
        raise DualReconciliationPending(
            "re-genesis broker handover requires the latest finalized clean "
            "RUNNING/COMPLETE reconciliation")
    if body.get("positions") != {} or body.get("provenance_positions") != []:
        raise DualReconciliationPending(
            "economic re-genesis is approved but the broker account is not "
            "flat; old-strategy positions must not be reinterpreted as the "
            "fresh Wealth Core/controller genesis")
    in_flight_states = {state.value for state in IN_FLIGHT}
    working = [
        str(order.get("id") or "UNKNOWN") for order in body.get("orders", [])
        if str(order.get("state") or "") in in_flight_states]
    if working:
        raise DualReconciliationPending(
            "re-genesis broker handover still has working order(s): "
            + ", ".join(sorted(working)[:8]))
    if binding is not None:
        identity = binding.identity
        if (str(body.get("broker") or "") != str(identity.broker)
                or str(body.get("broker_account_id") or "")
                != str(identity.broker_account_id)):
            raise DualReconciliationRefused(
                "re-genesis broker observation belongs to another account")


def _validate_handover(value: Any, *, segment, observation_id: str) -> dict:
    raw = dict(value) if isinstance(value, Mapping) else None
    expected = {
        "schema", "logical_observation_id", "segment_index",
        "segment_marker_sha256", "deployment_id", "broker",
        "broker_account_id", "takeover_epoch", "adopted_plan_id",
        "adopted_plan_fingerprint", "decision_session", "broker_observed_at",
        "broker_observation_seq", "broker_observation_sha256",
        "sizing_authority_sha256", "handover_sha256",
    }
    if raw is None or set(raw) != expected:
        raise DualReconciliationRefused(
            "re-genesis broker handover has an unknown shape")
    if raw.get("schema") != REGENESIS_HANDOVER_SCHEMA:
        raise DualReconciliationRefused(
            "re-genesis broker handover has an unknown schema")
    digest = str(raw.get("handover_sha256") or "")
    unsigned = dict(raw)
    unsigned.pop("handover_sha256", None)
    if _HEX64.fullmatch(digest) is None or digest != _sha256(unsigned):
        raise DualReconciliationRefused(
            "re-genesis broker handover digest is invalid")
    marker = str(raw.get("segment_marker_sha256") or "")
    if (raw.get("logical_observation_id") != str(observation_id)
            or raw.get("segment_index") != int(segment.index)
            or marker != str(segment.marker_sha256 or "")):
        raise DualReconciliationRefused(
            "re-genesis broker handover belongs to another shadow segment")
    for field in (
            "segment_marker_sha256", "sizing_authority_sha256",
            "adopted_plan_fingerprint", "broker_observation_sha256"):
        if _HEX64.fullmatch(str(raw.get(field) or "")) is None:
            raise DualReconciliationRefused(
                f"re-genesis broker handover {field} is malformed")
    for field in (
            "deployment_id", "broker", "broker_account_id", "adopted_plan_id"):
        if not isinstance(raw.get(field), str) or not str(raw[field]).strip():
            raise DualReconciliationRefused(
                f"re-genesis broker handover {field} is empty")
    if (isinstance(raw.get("takeover_epoch"), bool)
            or not isinstance(raw.get("takeover_epoch"), int)
            or int(raw["takeover_epoch"]) < 1):
        raise DualReconciliationRefused(
            "re-genesis broker handover takeover epoch is invalid")
    if (isinstance(raw.get("broker_observation_seq"), bool)
            or not isinstance(raw.get("broker_observation_seq"), int)
            or int(raw["broker_observation_seq"]) < 1):
        raise DualReconciliationRefused(
            "re-genesis broker handover observation sequence is invalid")
    try:
        observed = datetime.fromisoformat(str(raw["broker_observed_at"]))
        date.fromisoformat(str(raw["decision_session"]))
    except (TypeError, ValueError) as exc:
        raise DualReconciliationRefused(
            "re-genesis broker handover timestamp/session is malformed") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise DualReconciliationRefused(
            "re-genesis broker handover observation time is naive")
    return json.loads(_canonical(raw))


def _load_regenesis_handover(conn, *, segment, observation_id: str) -> dict | None:
    if segment.index == 0:
        return None
    cursor = _handover_cursor(observation_id, segment.index)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (cursor,))
        row = cur.fetchone()
    if row is None:
        return None
    value = row[1] if isinstance(row[1], Mapping) else json.loads(str(row[1]))
    result = _validate_handover(
        value, segment=segment, observation_id=observation_id)
    if str(row[0]) != str(result["decision_session"]):
        raise DualReconciliationRefused(
            "re-genesis broker handover session column disagrees with payload")
    evidence = _observation_evidence(
        conn, seq=int(result["broker_observation_seq"]))
    if evidence is None:
        raise DualReconciliationRefused(
            "re-genesis broker handover references a missing broker observation")
    body, evidence_sha, observed = evidence
    _require_flat_observation_body(body)
    if (evidence_sha != result["broker_observation_sha256"]
            or observed.isoformat() != str(result["broker_observed_at"])
            or body["broker"] != result["broker"]
            or body["broker_account_id"] != result["broker_account_id"]):
        raise DualReconciliationRefused(
            "re-genesis broker handover observation evidence changed")
    return result


def _require_handover_binding(receipt: Mapping, *, binding) -> None:
    """Economic handover follows the broker account, not a command epoch."""
    identity = binding.identity
    expected = (str(identity.broker), str(identity.broker_account_id))
    actual = (
        str(receipt.get("broker") or ""),
        str(receipt.get("broker_account_id") or ""))
    if actual != expected:
        raise DualReconciliationRefused(
            "re-genesis broker handover belongs to another broker account")


def _database_now(conn) -> datetime:
    with conn.cursor() as cur:
        cur.execute("SELECT clock_timestamp()")
        row = cur.fetchone()
    value = None if row is None else row[0]
    if not isinstance(value, datetime):
        raise DualReconciliationRefused(
            "database clock is unavailable for re-genesis handover")
    return _aware(value, label="database clock")


def _authority_floor_or_refuse(
        *, authority: Mapping, plan, binding,
        expected_sizing_authority_sha256: str) -> datetime:
    if (authority.get("plan_id") != plan.plan_id
            or authority.get("plan_fingerprint") != plan.fingerprint()
            or str(authority.get("decision_session")) != str(plan.decision_session)):
        raise DualReconciliationRefused(
            "re-genesis sizing authority does not name the current plan")
    authority_sha = str(authority.get("authority_sha256") or "")
    if (authority_sha != str(expected_sizing_authority_sha256)
            or _HEX64.fullmatch(authority_sha) is None):
        raise DualReconciliationRefused(
            "re-genesis sizing authority digest differs from re-derived plan")
    identity = binding.identity
    plan_identity = (
        str(plan.deployment_id), str(plan.broker),
        str(plan.broker_account_id), int(plan.takeover_epoch))
    binding_identity = (
        str(identity.deployment_id), str(identity.broker),
        str(identity.broker_account_id), int(identity.takeover_epoch))
    if plan_identity != binding_identity:
        raise DualReconciliationRefused(
            "re-genesis plan does not match the current account binding")
    observation = authority.get("broker_observation")
    if not isinstance(observation, Mapping):
        raise DualReconciliationRefused(
            "re-genesis sizing authority lacks broker observation evidence")
    account_identity = observation.get("account_identity")
    if (str(observation.get("completeness")) != "COMPLETE"
            or not isinstance(account_identity, Mapping)
            or str(account_identity.get("broker") or "") != str(identity.broker)
            or str(account_identity.get("account_id") or "")
            != str(identity.broker_account_id)):
        raise DualReconciliationRefused(
            "re-genesis sizing observation is incomplete or belongs to another account")
    try:
        observed = datetime.fromisoformat(str(observation.get("observed_at")))
    except (TypeError, ValueError) as exc:
        raise DualReconciliationRefused(
            "re-genesis sizing observation timestamp is malformed") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise DualReconciliationRefused(
            "re-genesis sizing observation timestamp is naive")
    return observed.astimezone(timezone.utc)


def _latest_clean_flat_observation_or_refuse(
        conn, *, binding, not_before: datetime):
    evidence = _observation_evidence(conn)
    if evidence is None:
        raise DualReconciliationPending(
            "re-genesis broker handover has no durable reconciliation observation")
    body, evidence_sha, observed = evidence
    _require_flat_observation_body(body, binding=binding)
    if observed < not_before:
        raise DualReconciliationPending(
            "latest clean flat broker reconciliation predates the immutable "
            "plan sizing observation")
    now = _database_now(conn)
    age = now - observed
    if age < timedelta(seconds=-5):
        raise DualReconciliationRefused(
            "re-genesis broker observation is materially future-dated")
    if age > timedelta(seconds=REGENESIS_HANDOVER_MAX_AGE_SECONDS):
        raise DualReconciliationPending(
            "flat broker reconciliation is too old to establish economic "
            "re-genesis; preparation must re-observe the broker")
    in_flight = journal.in_flight_commands(conn, binding.identity)
    if in_flight:
        raise DualReconciliationPending(
            "re-genesis broker handover still has durable Sentinel command(s) "
            "that can move the account")
    return body, evidence_sha, observed


def _record_or_require_regenesis_handover(
        conn, *, segment, observation_id: str, plan, binding,
        sizing_authority_sha256: str) -> dict | None:
    """Create one segment/account handover under the behavioral writer lock."""
    if segment.index == 0:
        return None
    existing = _load_regenesis_handover(
        conn, segment=segment, observation_id=observation_id)
    if existing is not None:
        _require_handover_binding(existing, binding=binding)
        if existing["sizing_authority_sha256"] != sizing_authority_sha256:
            raise DualReconciliationRefused(
                "re-genesis broker handover names another sizing authority")
        return existing
    with journal.writer_lock(conn):
        existing = _load_regenesis_handover(
            conn, segment=segment, observation_id=observation_id)
        if existing is not None:
            _require_handover_binding(existing, binding=binding)
            if existing["sizing_authority_sha256"] != sizing_authority_sha256:
                raise DualReconciliationRefused(
                    "re-genesis broker handover names another sizing authority")
            return existing
        authority = dual_plan_authority.load_authority(
            conn, plan_id=plan.plan_id)
        if authority is None:
            raise DualReconciliationPending(
                "re-genesis PAPER plan has no immutable sizing authority yet")
        floor = _authority_floor_or_refuse(
            authority=authority, plan=plan, binding=binding,
            expected_sizing_authority_sha256=sizing_authority_sha256)
        observation, observation_sha, observed = (
            _latest_clean_flat_observation_or_refuse(
                conn, binding=binding, not_before=floor))
        identity = binding.identity
        body = {
            "schema": REGENESIS_HANDOVER_SCHEMA,
            "logical_observation_id": str(observation_id),
            "segment_index": int(segment.index),
            "segment_marker_sha256": str(segment.marker_sha256 or ""),
            "deployment_id": str(identity.deployment_id),
            "broker": str(identity.broker),
            "broker_account_id": str(identity.broker_account_id),
            "takeover_epoch": int(identity.takeover_epoch),
            "adopted_plan_id": str(plan.plan_id),
            "adopted_plan_fingerprint": str(plan.fingerprint()),
            "decision_session": str(plan.decision_session),
            "broker_observed_at": observed.isoformat(),
            "broker_observation_seq": int(observation["observation_seq"]),
            "broker_observation_sha256": observation_sha,
            "sizing_authority_sha256": str(sizing_authority_sha256),
        }
        value = {**body, "handover_sha256": _sha256(body)}
        cursor = _handover_cursor(observation_id, segment.index)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO NOTHING",
                (cursor, str(plan.decision_session), _canonical(value)))
        stored = _load_regenesis_handover(
            conn, segment=segment, observation_id=observation_id)
        if stored != value:
            raise DualReconciliationRefused(
                "a concurrent writer recorded different re-genesis handover evidence")
        _require_handover_binding(stored, binding=binding)
        return stored


def verified_shadow_intent(
        conn, *, decision_session: date | str, observation_id: str,
        starting_cash: Decimal | str | int | float,
        allow_regenesis_handover_pending: bool = False):
    wanted = str(decision_session)
    try:
        result = shadow_runtime.verified_shadow_status(
            conn, observation_id=observation_id,
            starting_cash=starting_cash)
    except shadow_runtime.ShadowRuntimeRefused as exc:
        raise DualReconciliationRefused(
            f"certified shadow status is invalid: {exc}") from exc
    if result is None or result.session < wanted:
        raise DualReconciliationPending(
            "certified shadow has not attested the PAPER decision close")
    if result.session != wanted:
        raise DualReconciliationRefused(
            "certified shadow and PAPER intent name different decision closes")
    if (result.shadow_verdict != "SHADOW_GO"
            or result.verification != "VERIFIED"):
        raise DualReconciliationRefused(
            "shadow result is not currently SHADOW_GO/VERIFIED")
    state = result.state
    if state.last_processed_session != wanted:
        raise DualReconciliationRefused(
            "verified shadow state cursor differs from PAPER decision close")
    segment = _require_regenesis_transport_approval(conn, observation_id)
    allow_pending = (
        allow_regenesis_handover_pending or regenesis_preparation_active())
    if segment.index > 0 and not allow_pending:
        handover = _load_regenesis_handover(
            conn, segment=segment, observation_id=observation_id)
        if handover is None:
            current = journal.latest_plan(conn)
            if current is not None and str(current.decision_session) == wanted:
                raise DualReconciliationPending(
                    "post-gap PAPER transport has no durable flat broker handover; "
                    "broker mutation remains fenced")
    return result


def require_plan_matches_verified_shadow(
        conn, *, plan, observation_id: str,
        starting_cash: Decimal | str | int | float,
        binding=None, rollout_state=None,
        establish_regenesis_handover: bool = False) -> Mapping[str, str]:
    """Verify exact dual intent; optionally establish the one-time handover."""
    decision_session = str(plan.decision_session)
    result = verified_shadow_intent(
        conn, decision_session=decision_session,
        observation_id=observation_id, starting_cash=starting_cash,
        allow_regenesis_handover_pending=True)
    segment = shadow_segments.active_segment(conn, observation_id)
    state = result.state
    if str(plan.shadow_snapshot_hash) != state.state_hash:
        raise DualReconciliationRefused(
            "PAPER plan state hash differs from the certified shadow state")
    if int(plan.data_version) != int(state.data_version):
        raise DualReconciliationRefused(
            "PAPER plan data version differs from certified shadow state")
    decision = state.last_decision
    if (not isinstance(decision, Mapping)
            or decision.get("session") != decision_session):
        raise DualReconciliationRefused(
            "verified shadow lacks the current controller decision")
    expected_exposure = _decimal(
        decision.get("target_core_exposure"),
        label="verified shadow Core exposure")
    actual_exposure = _decimal(plan.target_exposure, label="PAPER plan Core exposure")
    if expected_exposure != actual_exposure:
        raise DualReconciliationRefused(
            "PAPER plan exposure differs from certified shadow intent")
    expected_effective = date.fromisoformat(calendar.next_session(decision_session))
    if plan.effective_session != expected_effective:
        raise DualReconciliationRefused(
            "PAPER plan is not bound to the certified following XNYS session")
    if binding is None:
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
    if rollout_state is None:
        from sentinel.authority import load_rollout_state
        rollout_state = load_rollout_state(conn)
    try:
        sizing = dual_plan_authority.rederive_plan(
            conn, plan=plan, binding=binding, rollout_state=rollout_state,
            expected_shadow_result=result)
    except dual_plan_authority.DualPlanAuthorityRefused as exc:
        raise DualReconciliationRefused(
            f"PAPER plan sizing authority is invalid: {exc}") from exc
    handover = None
    if segment.index > 0:
        if establish_regenesis_handover:
            if not regenesis_preparation_active():
                raise DualReconciliationRefused(
                    "re-genesis handover establishment is outside the explicit "
                    "production preparation scope")
            handover = _record_or_require_regenesis_handover(
                conn, segment=segment, observation_id=observation_id,
                plan=plan, binding=binding,
                sizing_authority_sha256=sizing["authority_sha256"])
        else:
            handover = _load_regenesis_handover(
                conn, segment=segment, observation_id=observation_id)
            if handover is None:
                raise DualReconciliationPending(
                    "post-gap PAPER plan has no durable flat broker handover; "
                    "read-only verification cannot create that authority")
            _require_handover_binding(handover, binding=binding)
            if handover["sizing_authority_sha256"] != sizing["authority_sha256"]:
                raise DualReconciliationRefused(
                    "re-genesis handover sizing authority differs from current plan")
    return {
        "schema": "sentinel.dual-plan-shadow-reconciliation/1",
        "decision_session": decision_session,
        "effective_session": expected_effective.isoformat(),
        "state_sha256": state.state_hash,
        "shadow_record_sha256": result.record_sha256,
        "shadow_runtime_authority_sha256": str(result.runtime_authority_sha256),
        "sizing_authority_sha256": sizing["authority_sha256"],
        "plan_fingerprint": sizing["plan_fingerprint"],
        "target_core_exposure": format(expected_exposure.normalize(), "f"),
        "performance_segment": str(segment.index),
        "segment_marker_sha256": str(segment.marker_sha256 or ""),
        "regenesis_handover_sha256": (
            "" if handover is None else str(handover["handover_sha256"])),
        "verdict": "MATCH",
    }


__all__ = [
    "DualReconciliationPending", "DualReconciliationRefused",
    "REGENESIS_APPROVAL_ENV", "REGENESIS_HANDOVER_MAX_AGE_SECONDS",
    "REGENESIS_HANDOVER_PREFIX", "REGENESIS_HANDOVER_SCHEMA",
    "REGENESIS_OBSERVATION_SCHEMA", "regenesis_preparation_active",
    "regenesis_preparation_scope", "require_plan_matches_verified_shadow",
    "verified_shadow_intent",
]
