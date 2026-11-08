"""One canonical shadow configuration, without financial runtime bootstrap."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
import re
from typing import Mapping, Optional

from sentinel.feed.observation_timing import POLICY

_OBSERVATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BROKER_AUTHORITY_ENV = (
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "SENTINEL_PAPER_ACCOUNT_ID")


class ShadowServiceRefused(RuntimeError):
    """The service cannot preserve an attributable shadow lineage."""


class ShadowServiceRetry(RuntimeError):
    """A vendor publication is not ready yet; retry without changing lineage."""


class ShadowServiceWaiting(RuntimeError):
    """No causally eligible first close exists yet; poll without writing."""


@dataclass(frozen=True)
class ShadowServiceConfig:
    database_url: str
    observation_id: str
    starting_cash: Decimal
    publication_timing_policy: str
    poll_seconds: int
    operational_source_only: bool = False

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None
                 ) -> "ShadowServiceConfig":
        source = os.environ if env is None else env
        operational_source_only = (
            str(source.get("SENTINEL_FEED_SERVICE_MODE") or "").strip()
            == "SHADOW")
        forbidden = ("SENTINEL_PAPER_ACCOUNT_ID",) if operational_source_only else _BROKER_AUTHORITY_ENV
        leaked = [name for name in forbidden if str(source.get(name) or "").strip()]
        if leaked:
            raise ShadowServiceRefused(
                "broker authority is forbidden in the shadow service environment")
        if operational_source_only:
            if not all(str(source.get(name) or "").strip() for name in (
                    "ALPACA_API_KEY", "ALPACA_SECRET_KEY")):
                raise ShadowServiceRefused(
                    "Alpaca market-data credentials are required for operational shadow")
            if str(source.get("SHARADAR_API_KEY") or "").strip():
                raise ShadowServiceRefused(
                    "Sharadar credentials are forbidden in operational shadow")
        enabled = str(source.get(
            "SENTINEL_SHADOW_OBSERVATION_ENABLED", "0")).strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise ShadowServiceRefused(
                "reviewed shadow observation is not explicitly enabled")
        reviewed_hashes = (
            "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256",
            "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256",
            "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256",
            "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256",
        )
        for name in reviewed_hashes:
            if _SHA256.fullmatch(str(source.get(name, "")).strip()) is None:
                raise ShadowServiceRefused("%s is required" % name)
        reviewed_mode = str(source.get(
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE", "")).strip().lower()
        if reviewed_mode not in {"shadow", "dual"}:
            raise ShadowServiceRefused(
                "SENTINEL_REVIEWED_DEPLOYMENT_MODE must authorize shadow or "
                "dual operation")
        database_url = str(source.get("SENTINEL_DATABASE_URL") or "").strip()
        if not database_url:
            raise ShadowServiceRefused("SENTINEL_DATABASE_URL is required")
        observation_id = str(source.get(
            "SENTINEL_SHADOW_OBSERVATION_ID", "primary")).strip()
        if _OBSERVATION_ID.fullmatch(observation_id) is None:
            raise ShadowServiceRefused("shadow observation id is malformed")
        try:
            starting_cash = Decimal(str(source.get(
                "SENTINEL_SHADOW_STARTING_CASH", "50000")).strip())
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ShadowServiceRefused(
                "shadow starting cash must be a positive decimal") from exc
        if not starting_cash.is_finite() or starting_cash <= 0:
            raise ShadowServiceRefused(
                "shadow starting cash must be a positive decimal")
        publication_timing_policy = str(source.get(
            "SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY",
            POLICY)).strip()
        if (publication_timing_policy
                != POLICY):
            raise ShadowServiceRefused(
                "shadow publication timing policy differs from review")
        try:
            poll_seconds = int(str(source.get(
                "SENTINEL_SHADOW_POLL_SECONDS", "300")).strip())
        except (TypeError, ValueError) as exc:
            raise ShadowServiceRefused(
                "SENTINEL_SHADOW_POLL_SECONDS must be an integer") from exc
        if poll_seconds < 5 or poll_seconds > 3600:
            raise ShadowServiceRefused(
                "SENTINEL_SHADOW_POLL_SECONDS must be in [5, 3600]")
        return cls(
            database_url, observation_id, starting_cash,
            publication_timing_policy, poll_seconds, operational_source_only)
