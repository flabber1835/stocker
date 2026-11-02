"""Public-file LIVE enrollment bridged to actual durable/runtime identities."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import os
from pathlib import Path

from sentinel import binding
from sentinel.execution.identity import ALPACA_LIVE_BROKER
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.execution.protected_limits import ProtectedLimitPolicy
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment

from . import repository
from .canonical import _b64url_decode, _parse_canonical_json, canonical_sha256, key_id_for_public_key
from .live import (
    LiveAdapterAdmission, LiveAuthorityContext, LiveTrustRoot,
    require_live_adapter_admission,
)
from .model import AuthorityRefused, MAX_CERTIFICATE_BYTES, RolloutMode
from .validation import runtime_artifact_identity


ENROLLMENT_SCHEMA = "sentinel.live-trust-enrollment/1"
CERTIFICATE_PATH_ENV = "SENTINEL_LIVE_CERTIFICATE_PATH"
TRUST_ROOTS_PATH_ENV = "SENTINEL_LIVE_TRUST_ROOTS_PATH"
_OPERATIONS = {
    "READ": "READ", "PREPARE_READ": "READ", "EXECUTE_READ": "READ",
    "AUTOMATION": "AUTOMATION", "SAFETY_READ": "READ",
    "SUBMIT": "SUBMIT", "CANCEL": "CANCEL", "SAFETY_CANCEL": "CANCEL",
}


def _hex(value, *, label: str) -> str:
    from .live import _digest

    if not _digest(value):
        raise AuthorityRefused(f"current LIVE {label} is missing or malformed")
    return value


def _path(env: Mapping[str, str], name: str) -> Path:
    value = env.get(name)
    if type(value) is not str or not value or value != value.strip():
        raise AuthorityRefused(f"{name} must name an explicit public enrollment file")
    path = Path(value)
    if not path.is_absolute():
        raise AuthorityRefused(f"{name} must be an absolute public file path")
    return path


def _public_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_CERTIFICATE_BYTES + 1)
    except OSError as exc:
        raise AuthorityRefused("LIVE public authority file is unavailable") from exc
    if not payload or len(payload) > MAX_CERTIFICATE_BYTES:
        raise AuthorityRefused("LIVE public authority file exceeds its byte bound")
    return payload


def _timestamp(value) -> datetime:
    if type(value) is not str:
        raise AuthorityRefused("LIVE enrollment timestamp is malformed")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorityRefused("LIVE enrollment timestamp is malformed") from exc
    if instant.utcoffset() is None:
        raise AuthorityRefused("LIVE enrollment timestamps must be timezone aware")
    return instant


def _enrollment(path: Path):
    raw = _parse_canonical_json(_public_bytes(path), label="LIVE public enrollment")
    if (set(raw) != {"schema", "roots", "revoked_certificate_sha256"}
            or raw["schema"] != ENROLLMENT_SCHEMA
            or type(raw["roots"]) is not list or len(raw["roots"]) > 64
            or type(raw["revoked_certificate_sha256"]) is not list
            or len(raw["revoked_certificate_sha256"]) > 4096):
        raise AuthorityRefused("LIVE public enrollment schema or bounds refused")
    roots = {}
    for record in raw["roots"]:
        if (not isinstance(record, Mapping)
                or set(record) != {"key_id", "public_key", "not_before", "not_after", "status", "scope"}
                or record["status"] not in {"DISABLED", "ENROLLED", "REVOKED"}
                or record["scope"] not in {"LIVE_EXECUTION", "LIVE_SETTLEMENT", "LIVE_ADMIN"}):
            raise AuthorityRefused("LIVE public root record is malformed")
        public_key = _b64url_decode(record["public_key"], label="LIVE public key", length=32)
        key_id = key_id_for_public_key(public_key)
        before, after = _timestamp(record["not_before"]), _timestamp(record["not_after"])
        if record["key_id"] != key_id or key_id in roots or before >= after:
            raise AuthorityRefused("LIVE public root identity or lifetime refused")
        roots[key_id] = LiveTrustRoot(public_key, before, after, record["status"], record["scope"])
    revoked = raw["revoked_certificate_sha256"]
    for digest in revoked:
        _hex(digest, label="certificate revocation")
    if len(set(revoked)) != len(revoked):
        raise AuthorityRefused("LIVE certificate revocations must be unique")
    return roots, frozenset(revoked)


def _subject(conn, endpoint: TradingEndpoint) -> ExecutionSubject:
    bound = binding.require(conn)
    if bound.broker != ALPACA_LIVE_BROKER:
        raise AuthorityRefused("LIVE URL requires an explicitly provisioned LIVE account binding")
    try:
        return ExecutionSubject(
            deployment_id=bound.deployment_id, account_id=bound.broker_account_id,
            takeover_epoch=bound.takeover_epoch, environment=endpoint.environment,
            base_url=endpoint.base_url)
    except ValueError as exc:
        raise AuthorityRefused("durable LIVE account subject is malformed") from exc


def _context(
        subject: ExecutionSubject, *, runtime_identity: Mapping, strategy_identity: Mapping,
        roots_path: Path, rollout, automation_config_sha256: str | None) -> LiveAuthorityContext:
    artifacts = runtime_artifact_identity(runtime_identity)
    environment = runtime_identity.get("environment")
    if (not isinstance(environment, Mapping) or environment.get("compatible") is not True
            or environment.get("pins_match") is not True or environment.get("sources_known") is not True
            or environment.get("pin_drift") != {}):
        raise AuthorityRefused("current LIVE runtime environment is not certified")
    source = environment.get("sentinel_source")
    if not isinstance(source, Mapping):
        raise AuthorityRefused("current LIVE runtime source is unavailable")
    if automation_config_sha256 is None:
        from sentinel.automation_runtime import config_from_env
        automation_config_sha256 = config_from_env().fingerprint
    _hex(automation_config_sha256, label="automation configuration")
    policy = ProtectedLimitPolicy.from_env()
    from sentinel.execution.issuer_admission import policy_sha256
    issuer_policy = policy_sha256({
        "deployment_id": subject.deployment_id, "broker": ALPACA_LIVE_BROKER,
        "broker_account_id": subject.account_id, "takeover_epoch": subject.takeover_epoch,
    })
    configuration = {
        "schema": "sentinel.live-execution-config/1",
        "environment": subject.environment.value, "base_url": subject.base_url,
        "broker": ALPACA_LIVE_BROKER,
        "trust_roots_sha256": hashlib.sha256(_public_bytes(roots_path)).hexdigest(),
        "automation_config_sha256": automation_config_sha256,
        "issuer_policy_sha256": _hex(issuer_policy, label="issuer admission policy"),
        "rollout_mode": rollout.mode.value, "rollout_version": rollout.version,
        "protected_buy_policy": None if policy is None else policy.to_dict(),
    }
    return LiveAuthorityContext(subject, {
        "runtime_image_digest": artifacts["runtime_image_digest"],
        "sentinel_source_sha256": _hex(source.get("hash"), label="source identity"),
        "runtime_identity_sha256": _hex(runtime_identity.get("identity_hash"), label="runtime identity"),
        "strategy_identity_sha256": canonical_sha256(strategy_identity),
        "execution_config_sha256": canonical_sha256(configuration),
    })


def load_live_adapter_admission(
        conn, *, base_url: str, runtime_identity: Mapping, strategy_identity: Mapping,
        automation_config_sha256: str | None = None,
        env: Mapping[str, str] | None = None, now: datetime | None = None) -> LiveAdapterAdmission:
    """No defaults enroll an issuer, establish ownership or change a database."""
    endpoint = TradingEndpoint.parse(base_url)
    if endpoint.environment is not TradingEnvironment.LIVE:
        raise AuthorityRefused("LIVE authority loader requires the exact LIVE origin")
    _subject(conn, endpoint)
    e = os.environ if env is None else env
    certificate_path = _path(e, CERTIFICATE_PATH_ENV)
    roots_path = _path(e, TRUST_ROOTS_PATH_ENV)
    def context_provider():
        subject = _subject(conn, endpoint)
        rollout = repository.load_rollout_state(conn)
        return _context(subject, runtime_identity=runtime_identity,
                        strategy_identity=strategy_identity, roots_path=roots_path,
                        rollout=rollout, automation_config_sha256=automation_config_sha256)

    admission = LiveAdapterAdmission(
        certificate=_public_bytes(certificate_path), context=context_provider(),
        trust_roots=lambda: _enrollment(roots_path)[0],
        revoked_certificate_sha256=lambda: _enrollment(roots_path)[1],
        certificate_provider=lambda: _public_bytes(certificate_path),
        context_provider=context_provider, enrollment_provider=lambda: _enrollment(roots_path))
    require_live_adapter_admission(admission, base_url=endpoint.base_url, now=now)
    return admission


def require_current_live_authority(
        conn, *, base_url: str, runtime_identity: Mapping, strategy_identity: Mapping,
        required_operation: str, automation_config_sha256: str | None = None,
        required_mode: RolloutMode | str | None = None, now: datetime | None = None,
        env: Mapping[str, str] | None = None):
    """Canonical callbacks supply fresh database/control/publication checks separately."""
    operation = _OPERATIONS.get(required_operation)
    if operation is None:
        raise AuthorityRefused("LIVE authority requires an exact broker operation")
    admission = load_live_adapter_admission(
        conn, base_url=base_url, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity, automation_config_sha256=automation_config_sha256, env=env, now=now)
    verified = require_live_adapter_admission(
        admission, base_url=base_url, now=now, required_operation=operation)
    rollout = repository.load_rollout_state(conn)
    if required_mode is not None and rollout.mode != RolloutMode(required_mode):
        raise AuthorityRefused("LIVE authority does not match the requested durable rollout")
    if rollout.mode is RolloutMode.CONTROLLER and rollout.certificate_sha256 != verified.sha256:
        raise AuthorityRefused("LIVE controller rollout names a different execution certificate")
    return verified
