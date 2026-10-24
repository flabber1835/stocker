"""File-evidence inventory for live preparation; never financial authority.

Hashes establish which supplied bytes were reviewed, not who produced them or
whether their claims are true. No current artifact profile has an independent
acceptance validator here, so even intact evidence remains REVIEW_REQUIRED.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
import hashlib
import re
from typing import Literal, Mapping
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_EVIDENCE_AGE = timedelta(days=1)


class Gate(str, Enum):
    OPENING_TIMING = 'opening_timing'
    BROKER_ACCOUNTING = 'broker_accounting'
    STRATEGY_ECONOMICS = 'strategy_economics'
    OPERATIONAL_RESILIENCE = 'operational_resilience'
    LIVE_ACCOUNT_AUTHORITY = 'live_account_authority'
    LIVE_PILOT = 'live_pilot'


class Scope(str, Enum):
    PRIVATE = 'PRIVATE_SIMULATION'
    PAPER = 'ALPACA_PAPER'
    LIVE_READ_ONLY = 'ALPACA_LIVE_READ_ONLY'
    LIVE_PILOT = 'ALPACA_LIVE_PILOT'


PROFILES = {
    Gate.OPENING_TIMING: 'OPENING_GATEWAY_MEASUREMENT_V1',
    Gate.BROKER_ACCOUNTING: 'BROKER_ACCOUNTING_CANDIDATE_V1',
    Gate.STRATEGY_ECONOMICS: 'STRATEGY_ECONOMIC_REVIEW_V1',
    Gate.OPERATIONAL_RESILIENCE: 'PRIVATE_PROCESS_RECOVERY_V1',
    Gate.LIVE_ACCOUNT_AUTHORITY: 'LIVE_ACCOUNT_REVIEW_V1',
    Gate.LIVE_PILOT: 'LIVE_PILOT_REVIEW_V1',
}
REMAINING_WORK = {
    Gate.OPENING_TIMING: 'Actual eligible-session original-clock execution and independent timing acceptance.',
    Gate.BROKER_ACCOUNTING: 'Native correction, action, fees, cash, settlement and interval-completeness acceptance.',
    Gate.STRATEGY_ECONOMICS: 'Independent economic certification for the exact selected strategy and data identities.',
    Gate.OPERATIONAL_RESILIENCE: 'Current-path failure/restart evidence and a separately approved live recovery policy.',
    Gate.LIVE_ACCOUNT_AUTHORITY: 'Separately reviewed live account binding, financial limits and explicit owner authority.',
    Gate.LIVE_PILOT: 'Separately authorized limited-capital native pilot and reconciled actual executions and costs.',
}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, revalidate_instances='always')


def _digest(value: str, length: int) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{' + str(length) + '}', value):
        raise ValueError('an exact lowercase digest is required')
    # Obvious test placeholders must not masquerade as an observed identity.
    if any(length % width == 0 and value == value[:width] * (length // width)
           for width in range(1, 9)):
        raise ValueError('placeholder identities are not evidence')
    return value


def _aware(value):
    if not isinstance(value, (datetime, str)):
        raise ValueError('an original aware datetime is required')
    return value


class CandidateSubject(_Frozen):
    profile: Literal['DISABLED_LIVE_PREPARATION_V1'] = 'DISABLED_LIVE_PREPARATION_V1'
    git_commit: str = Field(strict=True)
    source_sha256: str = Field(strict=True)
    image_digest: str = Field(strict=True)
    strategy_sha256: str = Field(strict=True)
    data_semantics_sha256: str = Field(strict=True)
    execution_policy_sha256: str = Field(strict=True)
    live_account_id: str | None = Field(default=None, strict=True)

    @field_validator('git_commit')
    @classmethod
    def exact_commit(cls, value):
        return _digest(value, 40)

    @field_validator('source_sha256', 'strategy_sha256', 'data_semantics_sha256', 'execution_policy_sha256')
    @classmethod
    def exact_digest(cls, value):
        return _digest(value, 64)

    @field_validator('image_digest')
    @classmethod
    def exact_image(cls, value):
        if not value.startswith('sha256:'):
            raise ValueError('an immutable image digest is required')
        _digest(value[7:], 64)
        return value

    @field_validator('live_account_id')
    @classmethod
    def exact_account(cls, value):
        if value is not None:
            parsed = UUID(value)
            if str(parsed) != value or parsed.int == 0:
                raise ValueError('an exact non-placeholder native account UUID is required')
        return value


class EvidenceReference(_Frozen):
    gate: Gate
    profile: str = Field(strict=True)
    scope: Scope
    subject: CandidateSubject
    artifact: str = Field(strict=True, min_length=1, max_length=128)
    artifact_sha256: str = Field(strict=True)
    observed_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator('artifact')
    @classmethod
    def simple_filename(cls, value):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value) or value in {'.', '..'}:
            raise ValueError('a simple evidence filename is required')
        return value

    @field_validator('artifact_sha256')
    @classmethod
    def exact_digest(cls, value):
        return _digest(value, 64)

    @field_validator('observed_at', 'expires_at', mode='before')
    @classmethod
    def original_clock(cls, value):
        return _aware(value)

    @model_validator(mode='after')
    def finite_profile(self):
        if self.profile != PROFILES[self.gate]:
            raise ValueError('evidence profile does not match its gate')
        if not timedelta(0) < self.expires_at - self.observed_at <= MAX_EVIDENCE_AGE:
            raise ValueError('evidence must retain a positive validity interval of at most one day')
        return self


class PreparationManifest(_Frozen):
    schema_id: Literal['sentinel.live-preparation-input/1'] = Field(
        default='sentinel.live-preparation-input/1', alias='schema')
    subject: CandidateSubject
    evidence: tuple[EvidenceReference, ...] = Field(default=(), max_length=64)

    @model_validator(mode='after')
    def unique_references(self):
        keys = [(item.gate, item.artifact) for item in self.evidence]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate gate/evidence references are not allowed')
        return self


class EvidenceAssessment(_Frozen):
    artifact: str
    artifact_sha256: str
    profile: str
    scope: Scope
    subject: CandidateSubject
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    status: Literal['REVIEW_REQUIRED', 'REJECTED']
    integrity_verified: bool = Field(strict=True)
    reasons: tuple[str, ...]


class GateAssessment(_Frozen):
    gate: Gate
    status: Literal['MISSING', 'REVIEW_REQUIRED', 'REJECTED']
    evidence: tuple[EvidenceAssessment, ...]
    remaining_work: str


class PreparationInventory(_Frozen):
    schema_id: Literal['sentinel.live-preparation-inventory/1'] = Field(
        default='sentinel.live-preparation-inventory/1', alias='schema')
    subject: CandidateSubject
    assessed_at: AwareDatetime
    status: Literal['NOT_QUALIFIED'] = 'NOT_QUALIFIED'
    live_authority_granted: Literal[False] = False
    live_transport_permitted: Literal[False] = False
    order_authority: Literal['NONE'] = 'NONE'
    provider_completeness_proven: Literal[False] = False
    native_settlement_proven: Literal[False] = False
    gates: tuple[GateAssessment, ...]
    unproven_gates: tuple[Gate, ...] = tuple(Gate)

    @model_validator(mode='after')
    def complete_unproven_inventory(self):
        if (tuple(item.gate for item in self.gates) != tuple(Gate)
                or self.unproven_gates != tuple(Gate)):
            raise ValueError('all six live gates must remain explicitly unproven')
        return self


def inventory(manifest: PreparationManifest, artifacts: Mapping[str, bytes], *,
              now: datetime) -> PreparationInventory:
    """Check supplied file integrity/scope, retaining every unproven gate.

    This does not parse artifact claims, authenticate a provider, accept a
    certificate, read configuration or instantiate any execution capability.
    """
    if not isinstance(manifest, PreparationManifest):
        raise TypeError('a typed preparation manifest is required')
    manifest = PreparationManifest.model_validate(manifest.model_dump(by_alias=True))
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError('an aware assessment clock is required')
    if not isinstance(artifacts, Mapping) or any(type(raw) is not bytes for raw in artifacts.values()):
        raise TypeError('file bytes are required')
    if sum(len(raw) for raw in artifacts.values()) > MAX_TOTAL_BYTES:
        raise ValueError('evidence exceeds the aggregate byte bound')
    groups = []
    for gate in Gate:
        assessed = []
        for reference in manifest.evidence:
            if reference.gate is not gate:
                continue
            reasons = []
            if reference.subject != manifest.subject:
                reasons.append('EXACT_SUBJECT_MISMATCH')
            if not reference.observed_at <= now < reference.expires_at:
                reasons.append('STALE_OR_FUTURE_EVIDENCE')
            raw = artifacts.get(reference.artifact)
            intact = (raw is not None and 0 < len(raw) <= MAX_ARTIFACT_BYTES
                      and hashlib.sha256(raw).hexdigest() == reference.artifact_sha256)
            if not intact:
                reasons.append('ARTIFACT_MISSING_OVERSIZED_OR_DIGEST_MISMATCH')
            if (reference.scope in {Scope.LIVE_READ_ONLY, Scope.LIVE_PILOT}
                    and manifest.subject.live_account_id is None):
                reasons.append('NATIVE_LIVE_ACCOUNT_NOT_BOUND')
            if gate in {Gate.LIVE_ACCOUNT_AUTHORITY, Gate.LIVE_PILOT}:
                expected_scope = Scope.LIVE_PILOT if gate is Gate.LIVE_PILOT else Scope.LIVE_READ_ONLY
                if reference.scope is not expected_scope:
                    reasons.append('PAPER_OR_PRIVATE_EVIDENCE_CANNOT_PROVE_LIVE_GATE')
                if (manifest.subject.live_account_id is None
                        and 'NATIVE_LIVE_ACCOUNT_NOT_BOUND' not in reasons):
                    reasons.append('NATIVE_LIVE_ACCOUNT_NOT_BOUND')
            assessed.append(EvidenceAssessment(
                artifact=reference.artifact, artifact_sha256=reference.artifact_sha256,
                profile=reference.profile, scope=reference.scope, subject=reference.subject,
                observed_at=reference.observed_at, expires_at=reference.expires_at,
                integrity_verified=intact,
                status='REJECTED' if reasons else 'REVIEW_REQUIRED',
                reasons=tuple(reasons) if reasons else ('CLAIMS_AND_PROVENANCE_NOT_INDEPENDENTLY_ACCEPTED',)))
        status = ('MISSING' if not assessed else
                  'REVIEW_REQUIRED' if any(item.status == 'REVIEW_REQUIRED' for item in assessed)
                  else 'REJECTED')
        groups.append(GateAssessment(gate=gate, status=status,
                                    evidence=tuple(assessed), remaining_work=REMAINING_WORK[gate]))
    return PreparationInventory(subject=manifest.subject, assessed_at=now, gates=tuple(groups))
