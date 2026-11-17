"""Settle exact owned PAPER commands while an installed upgrade stays killed.

This route has no plan, strategy, submission, cancellation, or kill-release
authority. The normal retained admission gate remains the final arbiter.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sentinel import identity, schema
from sentinel.automation import store as automation_store
from sentinel.authority import load_rollout_state, require_observation_safety_authority
from sentinel.config import SentinelConfig, assert_paper_url, build_execution_broker
from sentinel.execution import fill_integrity, fractional_progress, journal, reconcile, target_reprojection
from sentinel.execution.authority_gate import build_fresh_execution_guard
from sentinel.execution.contract import BrokerExactOrderLookup, BrokerObservation
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, BrokerOperation, FencedPaperRecoveryGrant,
    GuardedExecutionBroker,
)
from sentinel.execution.identity import is_sentinel_key
from sentinel.execution.states import CommandState, RuntimeState, blocks_overlapping
from sentinel.feed import calendar, store as feed_store
from sentinel.feed.rolling_contract import digest
from sentinel.handover import assert_no_legacy_path
from sentinel.paper.inspection import _require_certified_paper_broker
from sentinel.paper.targets import _action_lookup

SCHEMA = "sentinel.fenced-paper-command-recovery/1"
_AUTHORITY_ROOT = Path("/var/lib/sentinel-authority")


class FencedPaperRecoveryRefused(RuntimeError):
    """A missing exact recovery proof leaves activation disabled and killed."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise FencedPaperRecoveryRefused(reason)


def _pairs(items):
    value = {}
    for key, item in items:
        _require(key not in value, "installation receipt has duplicate keys")
        value[key] = item
    return value


def installation_receipt(*, path: str, sha256: str, account: str,
                         deployment: str, commit: str, image: str) -> dict:
    """Bind a read-only mounted receipt to the actual installed image."""
    root = _AUTHORITY_ROOT.resolve(strict=True)
    candidate = Path(path).resolve(strict=True)
    _require(candidate.is_relative_to(root) and candidate.is_file(),
             "installation receipt escaped the read-only authority mount")
    raw = candidate.read_bytes()
    _require(len(raw) <= 1024 * 1024 and hashlib.sha256(raw).hexdigest() == sha256,
             "installation receipt bytes changed")
    value = json.loads(raw, object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(
                           FencedPaperRecoveryRefused("nonfinite installation receipt")))
    _require(isinstance(value, dict)
             and value.get("schema") == "sentinel.installation-receipt/1"
             and value.get("installation_state") == "INSTALLED"
             and value.get("activation_state") == "FENCED"
             and value.get("automation_enabled") is False
             and value.get("kill_switch_engaged") is True
             and value.get("operational_ready") is False
             and value.get("requested_mode") in {"fenced", "dual", "paper"}
             and value.get("git_commit") == commit
             and value.get("runtime_image") == image
             and value.get("deployment_id") == deployment
             and value.get("paper_account_id") == account,
             "installation receipt is not this fenced PAPER deployment")
    actual = identity.rehearsal_identity()
    artifacts = actual["deployment_artifacts"]
    _require(actual["certification"]["certified"] is True
             and artifacts["git_commit"] == commit
             and os.environ.get("SENTINEL_IMAGE_SOURCE_REVISION") == commit
             and artifacts["runtime_image_digest"] == image.rsplit("@", 1)[-1]
             and image.endswith("@" + artifacts["runtime_image_digest"]),
             "installed executable source or image identity changed")
    return value


def _fence(conn, *, grant: FencedPaperRecoveryGrant | None,
           account: str, deployment: str, generation: int):
    bound = assert_no_legacy_path(conn)
    _require(bound.broker == "alpaca"
             and bound.broker_account_id == account
             and bound.deployment_id == deployment
             and bound.takeover_epoch == 1,
             "fenced recovery account, deployment or takeover differs")
    control = automation_store.load_control(conn)
    _require(not control.enabled and control.kill_switch_engaged
             and control.generation == generation,
             "fenced recovery requires exact disabled, killed control generation")
    lease = conn.execute(
        "SELECT holder_id,control_generation,expires_at"
        " FROM sentinel_automation_lease WHERE id=1").fetchone()
    _require(lease is not None and lease == (None, None, None),
             "fenced recovery requires an invalidated leader lease")
    if grant is not None:
        _require(grant.expected_account == account
                 and grant.deployment_id == deployment
                 and grant.takeover_epoch == bound.takeover_epoch
                 and grant.control_generation == generation,
                 "fenced recovery grant identity changed")
        _require(control.binding is not None
                 and control.binding.deployment_id == deployment
                 and control.binding.broker_account_id == account
                 and control.binding.takeover_epoch == bound.takeover_epoch
                 and control.binding.certificate_sha256 == grant.certificate_sha256,
                 "fenced recovery control binding changed")
    return bound, control


def _validate_read(conn, grant, operation: BrokerOperation, result,
                   *, account: str, deployment: str, generation: int,
                   base_url: str):
    _fence(conn, grant=grant, account=account,
           deployment=deployment, generation=generation)
    rollout = load_rollout_state(conn)
    certificate = require_observation_safety_authority(
        conn, required_operation="SAFETY_READ", required_mode=rollout.mode,
        paper_base_url=base_url)
    _require(certificate.certificate_sha256 == grant.certificate_sha256,
             "fenced recovery safety certificate changed")
    _require(os.environ.get("SENTINEL_GIT_COMMIT") == grant.git_commit
             and os.environ.get("SENTINEL_IMAGE_SOURCE_REVISION") == grant.git_commit
             and os.environ.get("SENTINEL_RUNTIME_IMAGE_DIGEST") == grant.runtime_image_digest,
             "fenced recovery installed image changed during broker read")
    _require(operation in {
        BrokerOperation.IDENTIFY_ACCOUNT,
        BrokerOperation.OBSERVE,
        BrokerOperation.FIND_BY_CLIENT_KEY,
        BrokerOperation.OWNED_ORDER_FILLS,
    }, "fenced recovery requested an unrelated broker read")
    if isinstance(result, BrokerObservation):
        _require(result.is_complete,
                 "fenced recovery broker observation is incomplete: "
                 + result.completeness.value)
        unknown = [order.client_key for order in result.orders
                   if is_sentinel_key(order.client_key)
                   and order.client_key not in grant.command_keys]
        unknown.extend(exact.client_key for exact in result.exact_order_evidence
                       if is_sentinel_key(exact.client_key)
                       and exact.client_key not in grant.command_keys)
        _require(not unknown, "fenced recovery observed an unowned Sentinel key")
    if isinstance(result, BrokerExactOrderLookup):
        _require(result.client_key in grant.command_keys,
                 "fenced recovery exact lookup changed its owned key")


def _native_coverage(conn, commands, *, native_plan_id: str | None) -> None:
    """A committed order status cannot substitute for its native executions."""
    for command in commands:
        if command.notional is not None and command.filled_quantity > 0:
            fill_integrity.exact_fill_economics(
                conn, command, verify_notional=True, require_cash=True)
            if command.identity.plan_id == native_plan_id:
                keys = [row[0] for row in conn.execute(
                    "SELECT fill_key FROM sentinel_fills"
                    " WHERE client_key=%s AND broker_order_id=%s",
                    (command.client_key, command.broker_order_id)).fetchall()]
                _require(keys and all(len(key) == 64 and
                                      all(ch in "0123456789abcdef" for ch in key)
                                      for key in keys),
                         "fenced recovery requires broker-native fill identities"
                         " for current fractional notional commands")


async def recover(*, config: SentinelConfig, installation_sha256: str,
                  account: str, deployment: str, generation: int,
                  image: str) -> dict:
    """Canonical read-only broker recovery with no new financial authority."""
    assert_paper_url(config.base_url)
    conn = feed_store.connect(config.database_url)
    try:
        schema.require_runtime_schema(conn)
        journal.require_observation_integrity(conn)
        with journal.writer_lock(conn, recovery_only=True):
            bound, control = _fence(
                conn, grant=None, account=account,
                deployment=deployment, generation=generation)
            commands = journal.load_commands(conn, bound.identity)
            keys = tuple(sorted(command.client_key for command in commands))
            _require(len(keys) == len(set(keys)), "fenced recovery command keys changed")
            in_flight = tuple(command for command in commands
                              if blocks_overlapping(command.state))
            _require(all(command.broker_order_id for command in in_flight),
                     "fenced recovery requires durable broker order IDs"
                     " for every in-flight command")
            order_ids = tuple(sorted((command.client_key, command.broker_order_id)
                                     for command in commands if command.broker_order_id))
            # The admission gate covers the whole journal, not only this binding.
            global_pending = conn.execute(
                "SELECT client_key FROM sentinel_commands WHERE state=ANY(%s)",
                ([state.value for state in CommandState
                  if blocks_overlapping(state)],)).fetchall()
            _require({row[0] for row in global_pending}
                     == {command.client_key for command in in_flight},
                     "fenced recovery has a foreign in-flight command")
            common = dict(
                schema=SCHEMA, installation_sha256=installation_sha256,
                git_commit=os.environ["SENTINEL_GIT_COMMIT"],
                runtime_image=image,
                deployment_id=deployment, paper_account_id=account,
                control_generation=generation,
                command_keys_sha256=digest(list(keys)),
                in_flight_commands=0, broker_mutations=False)
            plan = journal.latest_plan(conn)
            projection = (target_reprojection.load_projection(conn, plan_id=plan.plan_id)
                          if plan is not None else None)
            native_plan_id = (plan.plan_id if projection is not None
                              and fractional_progress.is_fractional(projection) else None)
            if not in_flight:
                _native_coverage(conn, commands, native_plan_id=native_plan_id)
                return dict(common, status="SKIPPED_CLEAN", observation_id=None)
            _require(keys, "fenced recovery has no owned command scope")
            _require(plan is not None and projection is not None
                     and fractional_progress.is_fractional(projection)
                     and all(command.identity.plan_id == plan.plan_id
                             for command in in_flight),
                     "fenced recovery requires the retained fractional command plan")
            rollout = load_rollout_state(conn)
            certificate = require_observation_safety_authority(
                conn, required_operation="SAFETY_READ", required_mode=rollout.mode,
                paper_base_url=config.base_url)
            _require(control.binding is not None
                     and control.binding.certificate_sha256 == certificate.certificate_sha256,
                     "fenced recovery control and signed authority differ")
            grant = FencedPaperRecoveryGrant(
                expected_account=account, deployment_id=deployment,
                takeover_epoch=bound.takeover_epoch,
                certificate_sha256=certificate.certificate_sha256,
                control_generation=generation,
                installation_sha256=installation_sha256,
                command_keys=keys,
                command_order_ids=order_ids,
                git_commit=os.environ["SENTINEL_GIT_COMMIT"],
                runtime_image_digest=os.environ["SENTINEL_RUNTIME_IMAGE_DIGEST"])
            symbols = {}
            for command in commands:
                symbol = command.instrument.symbol.upper()
                prior = symbols.setdefault(symbol, command.security_id)
                _require(prior == command.security_id,
                         "fenced recovery retained symbol has conflicting security identities")
            def resolver(symbol, _as_of=None):
                return symbols.get(str(symbol).upper())
            resolver.source_provider = "ALPACA_OPENFIGI"
            inner = build_execution_broker(config, resolve_security_id=resolver)
            _require_certified_paper_broker(inner, expected_wrapper_kind=None)
            _require(inner.supports_owned_order_fills is True,
                     "fenced recovery requires certified native fill reads")
            clock = lambda: datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
            guard = build_fresh_execution_guard(
                connection_factory=lambda: feed_store.connect(config.database_url),
                paper_base_url=config.base_url,
                runtime_identity=identity.rehearsal_identity,
                strategy_identity=lambda: {},
                validate_grant=lambda fresh, actual, operation, result: _validate_read(
                    fresh, actual, operation, result, account=account,
                    deployment=deployment, generation=generation,
                    base_url=config.base_url),
                publish_operational_evidence=False)
            broker = GuardedExecutionBroker(inner=inner, grant=grant, guard=guard)
            _require_certified_paper_broker(broker)
            _require(broker.supports_owned_order_fills is True,
                     "fenced recovery wrapper lost native fill capability")
            actions = _action_lookup(conn, None, clock().date())
            result = await reconcile.reconcile(
                broker=broker, conn=conn, binding=None,
                deployment=bound.identity, actions=actions,
                informational_current_book=True)
            _require(result.runtime_state is RuntimeState.RUNNING
                     and result.clean and result.observation is not None
                     and result.observation.is_complete,
                     "fenced recovery did not prove a complete clean account: "
                     + result.detail)
            _fence(conn, grant=grant, account=account,
                   deployment=deployment, generation=generation)
            _require(not journal.in_flight_commands(conn, bound.identity),
                     "fenced recovery left an overlapping command")
            _native_coverage(conn, journal.load_commands(conn, bound.identity),
                             native_plan_id=native_plan_id)
            return dict(common, status="RECONCILED",
                        observation_id=result.observation_id)
    finally:
        conn.close()
