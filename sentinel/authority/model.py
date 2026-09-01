"""Authority policy constants and immutable typed records."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Mapping


SIGNED_CERTIFICATE_SCHEMA = "sentinel.paper_execution_certificate/1"
OBSERVATION_CERTIFICATE_SCHEMA = "sentinel.paper_observation_certificate/1"
EMPTY_ACCOUNT_CERTIFICATE_SCHEMA = "sentinel.paper_empty_account_certificate/1"
TRUST_ROOTS_SCHEMA = "sentinel.ed25519_trust_roots/1"
SIGNED_CERTIFICATE_ALGORITHM = "Ed25519"
PAPER_SCOPE = "ALPACA_PAPER"
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
MAX_CERTIFICATE_BYTES = 1024 * 1024
MAX_CERTIFICATE_LIFETIME = timedelta(days=31)
DEFAULT_OBSERVATION_CERTIFICATE_LIFETIME = timedelta(days=31)
MAX_OBSERVATION_CERTIFICATE_LIFETIME = timedelta(days=35)
PAPER_OBSERVATION_ONLY = "PAPER_OBSERVATION_ONLY"
ADMIN_BIND_EMPTY = "ADMIN_BIND_EMPTY"
DEFAULT_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME = timedelta(minutes=15)
MAX_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME = timedelta(hours=1)
HISTORICAL_CAUSALITY_UNVERIFIED = "HISTORICAL_CAUSALITY_UNVERIFIED"
DEFAULT_TRUST_ROOTS_PATH = (
    Path(__file__).parent.parent / "trust_roots.json")


class AuthorityRefused(RuntimeError):
    """The durable certificate or rollout state cannot authorize execution."""


class RolloutMode(str, Enum):
    PINNED_1_00 = "PINNED_1_00"
    CONTROLLER = "CONTROLLER"


@dataclass(frozen=True)
class SystemCertificate:
    certificate_sha256: str
    manifest: Mapping
    allowed_rollout_modes: tuple[RolloutMode, ...]
    installed_at: object = None

    def allows(self, mode: RolloutMode) -> bool:
        return mode in self.allowed_rollout_modes


@dataclass(frozen=True)
class RolloutState:
    mode: RolloutMode
    version: int
    certificate_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RolloutMode):
            raise AuthorityRefused(f"unknown rollout mode {self.mode!r}")
        if not isinstance(self.version, int) or self.version < 1:
            raise AuthorityRefused("rollout version must be a positive integer")
        if (self.mode is RolloutMode.PINNED_1_00
                and self.certificate_sha256 is not None):
            raise AuthorityRefused(
                "pinned rollout state cannot carry controller authority")
        if (self.mode is RolloutMode.CONTROLLER
                and not self.certificate_sha256):
            raise AuthorityRefused(
                "controller rollout state requires certificate identity")

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "version": self.version,
            "certificate_sha256": self.certificate_sha256,
        }


@dataclass(frozen=True)
class SignedAuthorityContext:
    """All mutable runtime facts that a signed certificate is allowed to bind.

    ``bindings`` is compared as an exact canonical object.  It deliberately
    contains hashes rather than file paths or secrets.  Callers must compute it
    from the running image/configuration and approved publication policy; using
    values copied out of the certificate would turn the comparison into a
    tautology.
    """

    deployment_id: str
    broker: str
    broker_account_id: str
    takeover_epoch: int
    environment: str
    paper_base_url: str
    rollout_mode: RolloutMode
    rollout_version: int
    rollout_certificate_sha256: str | None
    bindings: Mapping

    def subject(self) -> dict:
        return {
            "deployment_id": self.deployment_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "takeover_epoch": self.takeover_epoch,
            "environment": self.environment,
            "paper_base_url": self.paper_base_url,
        }


@dataclass(frozen=True)
class TrustRoot:
    key_id: str
    public_key: bytes
    status: str
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True)
class SignedSystemCertificate:
    certificate_sha256: str
    envelope: Mapping
    claims: Mapping
    key_id: str
    status: str = "VERIFIED"
    installed_at: object = None
    install_sequence: int | None = None
    authority_generation: int | None = None

    @property
    def unattended_automation(self) -> bool:
        return bool(self.claims["unattended_automation"])

    @property
    def allowed_rollout_modes(self) -> tuple[RolloutMode, ...]:
        return tuple(RolloutMode(value)
                     for value in self.claims["allowed_rollout_modes"])

    @property
    def subject(self) -> Mapping:
        return self.claims["subject"]

    @property
    def rollout(self) -> Mapping:
        return self.claims["rollout"]

    def allows(self, mode: RolloutMode) -> bool:
        return mode in self.allowed_rollout_modes

    @property
    def authorization_mode(self) -> str:
        return str(self.claims.get(
            "authorization_mode", "HISTORICALLY_CERTIFIED"))

    @property
    def historical_causality(self) -> str:
        return str(self.claims.get(
            "historical_causality", "HISTORICALLY_CERTIFIED"))

    @property
    def maximum_exposure(self) -> Decimal:
        value = self.claims.get("maximum_exposure")
        return Decimal(1) if value is None else Decimal(str(value))
