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
  COMPLETE, flat, settled account with no order that could still move it.

The handover is recorded only from the immutable sizing observation created by
the current PAPER preparation and only while that observation is still fresh.
After it exists, later plans in the same segment may of course hold positions;
the account is not required to remain flat forever. A later segment has a new
marker and therefore requires a new flat handover.

Verification remains read-only by default. Only the explicit post-preparation
automation transition may set ``establish_regenesis_handover=True`` and mint the
one-time receipt. Inspection, recovery, and execution can verify an existing
receipt but cannot create one as a side effect of reading current plan state.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
from typing import Any, Mapping

from sentinel import dual_plan_authority, shadow_runtime, shadow_segments
from sentinel.execution import journal
from sentinel.execution.states import IN_FLIGHT
from sentinel.feed import calendar


REGENESIS_APPROVAL_ENV = "SENTINEL_SHADOW_REGENESIS_APPROVAL_SHA256"
REGENESIS_HANDOVER_SCHEMA = "sentinel.dual-regenesis-broker-handover/1"
REGENESIS_HANDOVER_PREFIX = "dual-regenesis-broker-handover:v1:"
REGENESIS_HANDOVER_MAX_AGE_SECONDS = 300
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")

# Dual reconciliation can run in automation, an authorized CLI, or tests. Every
# process must resolve the same active append-only segment as the shadow worker.
shadow_segments.install_runtime_store(shadow_runtime)


class DualReconciliationPending(RuntimeError):
    """The shadow service or explicit transport approval is not yet current."""


class DualReconciliationRefused(RuntimeError):
    """Shadow intent and PAPER transport authority do not match exactly."""


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


def _validate_handover(value: Any, *, segment, observation_id: str) -> dict:
    raw = dict(value) if isinstance(value, Mapping) else None
    expected = {
        "schema", "logical_observation_id", "segment_index",
        "segment_marker_sha256", "deployment_id", "broker",
        "broker_account_id", "takeover_epoch", "adopted_plan_id",
        "adopted_plan_fingerprint", "decision_session", "broker_observed_at",
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
    if _HEX64.fullmatch(marker) is None:
        raise DualReconciliationRefused(
            "re-genesis broker handover segment marker is malformed")
    if _HEX64.fullmatch(str(raw.get("sizing_authority_sha256") or "")) is None:
        raise DualReconciliationRefused(
            "re-genesis broker handover lacks sizing authority")
    if _HEX64.fullmatch(str(raw.get("adopted_plan_fingerprint") or "")) is None:
        raise DualReconciliationRefused(
            "re-genesis broker handover plan fingerprint is malformed")
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
    return result


def _require_handover_binding(receipt: Mapping, *, binding) -> None:
    """Economic handover follows the broker account, not a command epoch.

    ``deployment_id`` and ``takeover_epoch`` remain in the immutable receipt for
    audit, but a legitimate restored-host adoption changes the command namespace
    without changing the economic account or the shadow segment. Requiring the
    old epoch forever would deadlock a continuous strategy after a safe takeover.
    """
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
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _fresh_flat_authority_or_refuse(
        conn, *, authority: Mapping, plan, binding) -> datetime:
    """Prove the retained sizing read is a fresh flat broker handover."""
    if authority.get("plan_id") != plan.plan_id \
            or authority.get("plan_fingerprint") != plan.fingerprint():
        raise DualReconciliationRefused(
            "re-genesis sizing authority does not name the current plan")
    if str(authority.get("decision_session")) != str(plan.decision_session):
        raise DualReconciliationRefused(
            "re-genesis sizing authority names another decision session")

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
    if str(observation.get("completeness")) != "COMPLETE":
        raise DualReconciliationPending(
            "re-genesis broker handover requires a COMPLETE observation")
    account_identity = observation.get("account_identity")
    if (not isinstance(account_identity, Mapping)
            or str(account_identity.get("broker") or "") != str(identity.broker)
            or str(account_identity.get("account_id") or "")
            != str(identity.broker_account_id)):
        raise DualReconciliationRefused(
            "re-genesis broker observation belongs to another account")

    positions = observation.get("positions")
    orders = observation.get("orders")
    if not isinstance(positions, list) or not isinstance(orders, list):
        raise DualReconciliationRefused(
            "re-genesis broker observation position/order shape is invalid")
    if positions:
        raise DualReconciliationPending(
            "economic re-genesis is approved but the broker account is not "
            "flat; old-strategy positions must not be reinterpreted as the "
            "fresh Wealth Core/controller genesis")

    in_flight_states = {state.value for state in IN_FLIGHT}
    working = []
    replaced = []
    for order in orders:
        if not isinstance(order, Mapping):
            raise DualReconciliationRefused(
                "re-genesis broker order evidence is malformed")
        if bool(order.get("external_replacement")):
            replaced.append(str(order.get("broker_order_id") or "UNKNOWN"))
        if str(order.get("state") or "") in in_flight_states:
            working.append(str(order.get("broker_order_id") or "UNKNOWN"))
    if replaced:
        raise DualReconciliationRefused(
            "re-genesis broker handover observed externally replaced order(s): "
            + ", ".join(sorted(replaced)[:8]))
    if working:
        raise DualReconciliationPending(
            "re-genesis broker handover still has working order(s): "
            + ", ".join(sorted(working)[:8]))

    in_flight = journal.in_flight_commands(conn, identity)
    if in_flight:
        raise DualReconciliationPending(
            "re-genesis broker handover still has durable Sentinel command(s) "
            "that can move the account")

    try:
        observed = datetime.fromisoformat(str(observation.get("observed_at")))
    except (TypeError, ValueError) as exc:
        raise DualReconciliationRefused(
            "re-genesis broker observation timestamp is malformed") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise DualReconciliationRefused(
            "re-genesis broker observation timestamp is naive")
    now = _database_now(conn)
    age = now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)
    if age < timedelta(seconds=-5):
        raise DualReconciliationRefused(
            "re-genesis broker observation is materially future-dated")
    if age > timedelta(seconds=REGENESIS_HANDOVER_MAX_AGE_SECONDS):
        raise DualReconciliationPending(
            "flat broker evidence is too old to establish economic re-genesis; "
            "a later close must obtain a new flat sizing observation")
    return observed


def _record_or_require_regenesis_handover(
        conn, *, segment, observation_id: str, plan, binding) -> dict | None:
    """Create one segment handover under Sentinel's single behavioral writer."""
    if segment.index == 0:
        return None
    existing = _load_regenesis_handover(
        conn, segment=segment, observation_id=observation_id)
    if existing is not None:
        _require_handover_binding(existing, binding=binding)
        return existing

    # The sizing observation can say "flat" only at one instant. Holding the
    # same session-level writer lock used by plans/commands closes the race where
    # another process creates SEND_PENDING after that check but before the
    # handover row becomes durable. Recheck the unique receipt after acquiring
    # the lock so two legitimate restart attempts stay idempotent.
    with journal.writer_lock(conn):
        existing = _load_regenesis_handover(
            conn, segment=segment, observation_id=observation_id)
        if existing is not None:
            _require_handover_binding(existing, binding=binding)
            return existing

        authority = dual_plan_authority.load_authority(
            conn, plan_id=plan.plan_id)
        if authority is None:
            raise DualReconciliationPending(
                "re-genesis PAPER plan has no immutable sizing observation yet")
        observed = _fresh_flat_authority_or_refuse(
            conn, authority=authority, plan=plan, binding=binding)
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
            "sizing_authority_sha256": str(authority["authority_sha256"]),
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
                "a concurrent writer recorded different re-genesis handover "
                "evidence")
        _require_handover_binding(stored, binding=binding)
        # writer_lock commits only after the complete proof succeeds.
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
    if segment.index > 0 and not allow_regenesis_handover_pending:
        handover = _load_regenesis_handover(
            conn, segment=segment, observation_id=observation_id)
        if handover is None:
            current = journal.latest_plan(conn)
            if current is not None and str(current.decision_session) == wanted:
                raise DualReconciliationPending(
                    "the current post-gap PAPER plan has no durable flat broker "
                    "handover; broker mutation remains fenced")
    return result


def require_plan_matches_verified_shadow(
        conn, *, plan, observation_id: str,
        starting_cash: Decimal | str | int | float,
        binding=None, rollout_state=None,
        establish_regenesis_handover: bool = False) -> Mapping[str, str]:
    """Verify exact dual intent; optionally establish the one-time handover.

    ``False`` is the default so inspection/recovery/execution stay read-only at
    this layer. The caller that just completed current PAPER preparation may set
    the flag to ``True``; only that path may convert its fresh immutable sizing
    observation into the durable segment/account handover receipt.
    """
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
    actual_exposure = _decimal(
        plan.target_exposure, label="PAPER plan Core exposure")
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
    handover = None
    if segment.index > 0:
        if establish_regenesis_handover:
            handover = _record_or_require_regenesis_handover(
                conn, segment=segment, observation_id=observation_id,
                plan=plan, binding=binding)
        else:
            handover = _load_regenesis_handover(
                conn, segment=segment, observation_id=observation_id)
            if handover is None:
                raise DualReconciliationPending(
                    "post-gap PAPER plan has no durable flat broker handover; "
                    "read-only verification cannot create that authority")
            _require_handover_binding(handover, binding=binding)
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

    return {
        "schema": "sentinel.dual-plan-shadow-reconciliation/1",
        "decision_session": decision_session,
        "effective_session": expected_effective.isoformat(),
        "state_sha256": state.state_hash,
        "shadow_record_sha256": result.record_sha256,
        "shadow_runtime_authority_sha256": str(
            result.runtime_authority_sha256),
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
    "require_plan_matches_verified_shadow", "verified_shadow_intent",
]
