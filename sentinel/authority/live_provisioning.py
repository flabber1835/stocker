"""Attended empty LIVE enrollment; no takeover, broker mutation or rollout edit."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel import binding
from sentinel.automation import store as automation_store
from sentinel.automation.model import ControlBinding
from sentinel.execution import journal
from sentinel.execution.live_funding import FundingEvidence
from sentinel.execution.native_readonly import ExecutionSubject, ReadOnlyAlpacaClient
from sentinel.ownership import OwnershipState
from sentinel.store import PostgresOwnershipStore, record
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment

from . import repository
from .live import (
    LiveAdapterAdmission, LiveAuthorityContext, _bindings,
    verify_live_envelope,
)
from .live_runtime import (
    TRUST_ROOTS_PATH_ENV, _context, _enrollment, _path, _public_bytes,
    require_current_live_authority,
)
from .model import AuthorityRefused, RolloutMode


LIVE_ADMIN_SCHEMA = "sentinel.live_administrative_certificate/1"
PROVISIONING_PATH_ENV = "SENTINEL_LIVE_PROVISIONING_CERTIFICATE_PATH"


class LiveProvisioningClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    certificate_id: str = Field(strict=True, min_length=1, max_length=128)
    issued_at: AwareDatetime
    not_before: AwareDatetime
    expires_at: AwareDatetime
    subject: ExecutionSubject
    runtime_bindings: dict[str, str]
    permitted_operations: tuple[Literal["BIND_EMPTY_LIVE"], ...] = Field(min_length=1, max_length=1)

    @field_validator("runtime_bindings", mode="before")
    @classmethod
    def exact_runtime(cls, value):
        return _bindings(value)

    @field_validator("issued_at", "not_before", "expires_at", mode="before")
    @classmethod
    def aware_clock(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("original aware LIVE provisioning clocks are required")
        return value

    @model_validator(mode="after")
    def exact_bootstrap(self):
        if self.subject.environment is not TradingEnvironment.LIVE or self.subject.takeover_epoch != 1:
            raise ValueError("fresh LIVE provisioning requires the exact LIVE epoch-one subject")
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("LIVE provisioning clocks must be ordered")
        if self.expires_at - self.issued_at > timedelta(hours=1):
            raise ValueError("LIVE provisioning authority may last at most one hour")
        return self


@dataclass(frozen=True)
class LiveProvisioningAdmission(LiveAdapterAdmission):
    """Disjoint administrative envelope; the execution validator refuses this type."""


def require_live_provisioning_admission(admission: LiveProvisioningAdmission, *, now: datetime):
    if type(admission) is not LiveProvisioningAdmission:
        raise AuthorityRefused("separate LIVE provisioning authority is required")
    context = admission.context_provider() if admission.context_provider is not None else admission.context
    if type(context) is not LiveAuthorityContext:
        raise AuthorityRefused("actual LIVE provisioning context is unavailable")
    if admission.enrollment_provider is not None:
        roots, revoked = admission.enrollment_provider()
    else:
        roots = admission.trust_roots() if callable(admission.trust_roots) else admission.trust_roots
        revoked = (admission.revoked_certificate_sha256()
                   if callable(admission.revoked_certificate_sha256) else admission.revoked_certificate_sha256)
    payload = admission.certificate_provider() if admission.certificate_provider is not None else admission.certificate
    signed = verify_live_envelope(payload, schema=LIVE_ADMIN_SCHEMA, trust_roots=roots,
                                  now=now, root_scope="LIVE_ADMIN", revoked_certificate_sha256=revoked)
    try:
        claims = LiveProvisioningClaims.model_validate(signed.claims)
        subject = ExecutionSubject.model_validate(context.subject.model_dump())
        actual_bindings = _bindings(context.runtime_bindings)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AuthorityRefused("LIVE provisioning claims or context are invalid") from exc
    if claims.subject != subject or claims.runtime_bindings != actual_bindings:
        raise AuthorityRefused("LIVE provisioning subject or current runtime differs")
    if not claims.not_before <= now < claims.expires_at:
        raise AuthorityRefused("LIVE provisioning authority is not current")
    root = roots[signed.key_id]
    if claims.issued_at < root.not_before or claims.expires_at > root.not_after:
        raise AuthorityRefused("LIVE provisioning authority outlives its enrolled issuer")
    return signed, claims


def load_live_provisioning_admission(
        conn, *, base_url: str, deployment_id: str, expected_account: str,
        runtime_identity: Mapping, strategy_identity: Mapping,
        automation_config_sha256: str | None = None,
        env: Mapping[str, str] | None = None, now: datetime | None = None):
    endpoint = TradingEndpoint.parse(base_url)
    if endpoint.environment is not TradingEnvironment.LIVE or binding.load(conn) is not None:
        raise AuthorityRefused("LIVE provisioning requires a fresh unbound LIVE deployment")
    subject = ExecutionSubject(deployment_id=deployment_id, account_id=expected_account,
                               takeover_epoch=1, environment=endpoint.environment, base_url=endpoint.base_url)
    rollout = repository.load_rollout_state(conn)
    if rollout.mode is not RolloutMode.PINNED_1_00 or rollout.certificate_sha256 is not None:
        raise AuthorityRefused("LIVE provisioning requires the initial inert rollout")
    e = os.environ if env is None else env
    certificate_path = _path(e, PROVISIONING_PATH_ENV)
    roots_path = _path(e, TRUST_ROOTS_PATH_ENV)

    def context_provider():
        return _context(subject, runtime_identity=runtime_identity, strategy_identity=strategy_identity,
                        roots_path=roots_path, rollout=rollout, automation_config_sha256=automation_config_sha256)

    admission = LiveProvisioningAdmission(
        _public_bytes(certificate_path), context_provider(),
        certificate_provider=lambda: _public_bytes(certificate_path), context_provider=context_provider,
        enrollment_provider=lambda: _enrollment(roots_path))
    require_live_provisioning_admission(admission, now=now or datetime.now(timezone.utc))
    return admission


def _inert(conn, *, lock_control=False):
    if binding.load(conn) is not None:
        raise AuthorityRefused("LIVE provisioning refuses an existing account binding")
    control = automation_store.load_control(conn, for_update=lock_control)
    if control.enabled or not control.kill_switch_engaged or control.binding is not None:
        raise AuthorityRefused("LIVE provisioning requires disabled, killed, unbound automation")
    with conn.cursor() as cur:
        cur.execute("SELECT holder_id,expires_at FROM sentinel_automation_lease WHERE id=1")
        lease = cur.fetchone()
        if lease is None or lease[0] is not None or lease[1] is not None:
            raise AuthorityRefused("LIVE provisioning requires no existing lease")
        cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_commands) OR "
                    "EXISTS(SELECT 1 FROM sentinel_fills) OR "
                    "EXISTS(SELECT 1 FROM sentinel_execution_plans) OR "
                    "EXISTS(SELECT 1 FROM sentinel_ownership_events WHERE state=%s)",
                    (OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED.value,))
        history = cur.fetchone()
        if history is None or history[0] is not False:
            raise AuthorityRefused("LIVE provisioning refuses financial or prior ownership history")
    return control.generation


def _account_facts(raw, subject):
    if not isinstance(raw, Mapping) or raw.get("id") != subject.account_id or raw.get("status") != "ACTIVE":
        raise AuthorityRefused("LIVE provisioning account identity or status differs")
    flags = ("trading_blocked", "account_blocked", "trade_suspended_by_user")
    if any(raw.get(name) is not False for name in flags):
        raise AuthorityRefused("LIVE provisioning account availability is unproven")
    facts = {}
    try:
        for name in ("cash", "equity", "buying_power", "multiplier", "long_market_value", "short_market_value"):
            value = raw.get(name)
            if not isinstance(value, (str, Decimal)):
                raise ValueError("exact monetary account evidence is required")
            facts[name] = FundingEvidence.exact_money(value)
    except (ValueError, TypeError) as exc:
        raise AuthorityRefused("LIVE provisioning account economics are malformed") from exc
    if (facts["multiplier"] != 1 or facts["cash"] < 0
            or not 0 <= facts["buying_power"] <= facts["cash"]
            or facts["equity"] != facts["cash"] or facts["long_market_value"] != 0
            or facts["short_market_value"] != 0):
        raise AuthorityRefused("LIVE provisioning requires an empty unlevered account")
    return facts


async def _empty_observation(client, admission, clock):
    _, claims = require_live_provisioning_admission(admission, now=clock())
    if client.subject != claims.subject:
        raise AuthorityRefused("GET-only client belongs to another LIVE subject")

    async def get(path, params=None):
        require_live_provisioning_admission(admission, now=clock())
        return await client.get(path, params)

    first = _account_facts(await get("/v2/account"), claims.subject)
    for path, params in (("/v2/orders", {"status": "open", "limit": 1}),
                         ("/v2/positions", None),
                         ("/v2/orders", {"status": "open", "limit": 1})):
        result = await get(path, params)
        if type(result) is not list or result:
            raise AuthorityRefused("LIVE provisioning refuses a nonempty or unreadable broker book")
    last = _account_facts(await get("/v2/account"), claims.subject)
    if first != last:
        raise AuthorityRefused("LIVE account facts changed during empty-book observation")
    return first


async def bind_empty_live_account(
        conn, *, client: ReadOnlyAlpacaClient, admission: LiveProvisioningAdmission,
        confirm_live_account: str, confirm_deployment: str, confirm_empty_live_account: bool,
        actor: str, reason: str, clock=lambda: datetime.now(timezone.utc),
        poll_seconds: float = 1, sleep=asyncio.sleep):
    if type(client) is not ReadOnlyAlpacaClient or confirm_empty_live_account is not True:
        raise AuthorityRefused("attended LIVE empty-account confirmation and GET-only client are required")
    signed, claims = require_live_provisioning_admission(admission, now=clock())
    if confirm_live_account != claims.subject.account_id or confirm_deployment != claims.subject.deployment_id:
        raise AuthorityRefused("LIVE provisioning account/deployment confirmations differ")
    if type(actor) is not str or not actor.strip() or type(reason) is not str or not reason.strip():
        raise AuthorityRefused("LIVE provisioning requires an actor and reason")
    if type(poll_seconds) not in (int, float) or not 0 < poll_seconds <= 5:
        raise AuthorityRefused("LIVE provisioning observation interval must be positive and bounded")
    try:
        with journal.writer_lock(conn):
            generation = _inert(conn)
            first = await _empty_observation(client, admission, clock)
            await sleep(poll_seconds)
            second = await _empty_observation(client, admission, clock)
            if first != second:
                raise AuthorityRefused("LIVE account facts changed between empty-book observations")
            final_signed, final_claims = require_live_provisioning_admission(admission, now=clock())
            if final_signed.sha256 != signed.sha256 or final_claims != claims:
                raise AuthorityRefused("LIVE provisioning authority changed during observation")
            if _inert(conn, lock_control=True) != generation:
                raise AuthorityRefused("LIVE provisioning control changed during observation")
            record(PostgresOwnershipStore(conn, autocommit=False), OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED,
                   reason=reason, actor=actor, deployment_id=claims.subject.deployment_id,
                   broker_account_id=claims.subject.account_id,
                   provisioning_certificate_sha256=signed.sha256, environment="ALPACA_LIVE")
            binding.bind(conn, deployment_id=claims.subject.deployment_id, broker="alpaca-live",
                         broker_account_id=claims.subject.account_id, notes=reason, commit=False)
            conn.commit()
            return binding.require(conn)
    except BaseException:
        conn.rollback()
        raise


def _execution_activation_subject(conn, *, base_url, runtime_identity, strategy_identity,
                                  automation_config_sha256, confirm_live_account,
                                  confirm_deployment, confirm_real_money, env=None, now=None):
    bound = binding.require(conn)
    if (confirm_real_money is not True or bound.broker != "alpaca-live"
            or confirm_live_account != bound.broker_account_id or confirm_deployment != bound.deployment_id):
        raise AuthorityRefused("explicit real-money account/deployment confirmation is required")
    verified = require_current_live_authority(conn, base_url=base_url, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity, automation_config_sha256=automation_config_sha256,
        required_operation="AUTOMATION", env=env, now=now)
    for operation in ("SUBMIT", "CANCEL"):
        current = require_current_live_authority(conn, base_url=base_url, runtime_identity=runtime_identity,
            strategy_identity=strategy_identity, automation_config_sha256=automation_config_sha256,
            required_operation=operation, env=env, now=now)
        if current.sha256 != verified.sha256:
            raise AuthorityRefused("LIVE execution authority changed during activation")
    rollout = repository.load_rollout_state(conn)
    return ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        certificate_sha256=verified.sha256, rollout_mode=rollout.mode.value,
        rollout_version=rollout.version, config_sha256=automation_config_sha256)


def activate_live_automation(conn, *, actor: str, reason: str, **context):
    """Explicit activation retains the kill switch; no broker call is made."""
    with journal.writer_lock(conn):
        control_binding = _execution_activation_subject(conn, **context)
        return automation_store.activate(conn, binding=control_binding, actor=actor, reason=reason)


def release_live_kill(conn, *, actor: str, reason: str, **context):
    """Second confirmed transition; all ordinary membrane checks still apply."""
    with journal.writer_lock(conn):
        control_binding = _execution_activation_subject(conn, **context)
        return automation_store.release_kill(conn, expected_binding=control_binding, actor=actor, reason=reason)
