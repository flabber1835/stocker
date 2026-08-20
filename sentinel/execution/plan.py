"""The immutable record of what a decision was trying to achieve.

A plan is created when a session's decision is accepted, and it is never edited.
If a newer session decides something different before the previous plan has
completed, a NEW plan is created and may supersede the old one's UNSENT commands.
Working orders are not superseded — they are cancelled and confirmed cancelled,
because declaring a live order superseded abandons it.

This is what makes the question answerable after the fact:

> what exactly was Sentinel trying to accomplish when it placed this order?

Every field below is part of that answer, and `data_version` is the one that is
easy to leave out and impossible to reconstruct later: without it, a replay that
disagrees with history cannot say whether the broker drifted or the corpus moved.
That is architecture invariant #3, and it is why the column is NOT nullable in
spirit even though the schema tolerates NULL during the transition.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Mapping, Optional


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    decision_session: date
    effective_session: date
    target_exposure: Decimal
    target_basket: Mapping[str, Decimal] = field(default_factory=dict)
    data_version: Optional[int] = None
    shadow_snapshot_hash: str = ""
    sentinel_transition_hash: str = ""
    strategy_fingerprint: str = ""
    deployment_id: str = ""
    broker: str = ""
    broker_account_id: str = ""
    takeover_epoch: int = 0
    publication_fingerprint: str = ""
    account_nav: Decimal = Decimal(0)
    account_cash: Decimal = Decimal(0)
    cash_residual: Decimal = Decimal(0)
    unpriced_securities: tuple[str, ...] = ()
    defensive_security: Optional[str] = None
    rollout_mode: str = "PINNED_1_00"
    rollout_version: int = 1
    rollout_certificate_sha256: Optional[str] = None
    superseded_by: Optional[str] = None

    def __post_init__(self) -> None:
        scalars = (
            ("target_exposure", self.target_exposure),
            ("account_nav", self.account_nav),
            ("account_cash", self.account_cash),
            ("cash_residual", self.cash_residual),
        )
        for label, value in scalars:
            if not isinstance(value, Decimal):
                raise TypeError(f"{label} must be Decimal")
            if not value.is_finite():
                raise ValueError(f"{label} must be finite, got {value}")
        if self.rollout_mode not in {"PINNED_1_00", "CONTROLLER"}:
            raise ValueError(f"unknown rollout_mode {self.rollout_mode!r}")
        if not isinstance(self.rollout_version, int) or self.rollout_version < 1:
            raise ValueError("rollout_version must be a positive integer")
        if (self.rollout_mode == "PINNED_1_00"
                and self.rollout_certificate_sha256 is not None):
            raise ValueError(
                "pinned rollout plan cannot carry controller authority")
        if (self.rollout_mode == "CONTROLLER"
                and not self.rollout_certificate_sha256):
            raise ValueError(
                "controller rollout plan requires certificate identity")
        for security_id, qty in self.target_basket.items():
            if not isinstance(qty, Decimal):
                raise TypeError(
                    f"target_basket[{security_id}] must be Decimal, got "
                    f"{type(qty).__name__}")
            if not qty.is_finite():
                raise ValueError(
                    f"target_basket[{security_id}] must be finite, got {qty}")

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by is not None

    def fingerprint(self) -> str:
        """A stable hash of the plan's ECONOMIC content.

        Excludes `plan_id` and `superseded_by` — the first is an arbitrary
        handle and the second is a fact about what happened afterwards, so
        including either would make two plans with identical intent look
        different. Used to detect that a re-derived plan is unchanged, which is
        what lets an idempotent retry be recognised as one.
        """
        payload = {
            "decision_session": self.decision_session.isoformat(),
            "effective_session": self.effective_session.isoformat(),
            "target_exposure": str(self.target_exposure),
            "target_basket": {k: str(v)
                              for k, v in sorted(self.target_basket.items())},
            "data_version": self.data_version,
            "shadow_snapshot_hash": self.shadow_snapshot_hash,
            "sentinel_transition_hash": self.sentinel_transition_hash,
            "strategy_fingerprint": self.strategy_fingerprint,
            "deployment_id": self.deployment_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "takeover_epoch": self.takeover_epoch,
            "publication_fingerprint": self.publication_fingerprint,
            "account_nav": str(self.account_nav),
            "account_cash": str(self.account_cash),
            "cash_residual": str(self.cash_residual),
            "unpriced_securities": sorted(self.unpriced_securities),
            "defensive_security": self.defensive_security,
            "rollout_mode": self.rollout_mode,
            "rollout_version": self.rollout_version,
            "rollout_certificate_sha256": self.rollout_certificate_sha256,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        # This digest is also the production plan id suffix. Truncating it to
        # 64 bits made a hash collision a mutation-authority bypass: two
        # different economic baskets could share one durable id. Keep the full
        # SHA-256 so plan identity has the same strength as the source and
        # certification identities it carries.
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "decision_session": self.decision_session.isoformat(),
            "effective_session": self.effective_session.isoformat(),
            "target_exposure": str(self.target_exposure),
            "target_basket": {k: str(v)
                              for k, v in sorted(self.target_basket.items())},
            "data_version": self.data_version,
            "shadow_snapshot_hash": self.shadow_snapshot_hash,
            "sentinel_transition_hash": self.sentinel_transition_hash,
            "strategy_fingerprint": self.strategy_fingerprint,
            "deployment": {
                "deployment_id": self.deployment_id,
                "broker": self.broker,
                "broker_account_id": self.broker_account_id,
                "takeover_epoch": self.takeover_epoch,
            },
            "publication_fingerprint": self.publication_fingerprint,
            "account_nav": str(self.account_nav),
            "account_cash": str(self.account_cash),
            "cash_residual": str(self.cash_residual),
            "unpriced_securities": sorted(self.unpriced_securities),
            "defensive_security": self.defensive_security,
            "rollout": {
                "mode": self.rollout_mode,
                "version": self.rollout_version,
                "certificate_sha256": self.rollout_certificate_sha256,
            },
            "fingerprint": self.fingerprint(),
            "superseded_by": self.superseded_by,
        }