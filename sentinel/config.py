"""URL-selected execution configuration and explicit PAPER-only operations.

The exact trading origin selects the environment. LIVE transport additionally
requires independently signed, account-bound admission; selecting a URL never
grants order authority. Administrative PAPER operations retain their allowlist.

Credentials come from the environment only. Nothing here reads or writes a repo
file, and none of these values are ever logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from sentinel.trading_environment import (
    TradingEndpoint, TradingEndpointRefused, TradingEnvironment,
)

DEFAULT_BASE_URL = "https://paper-api.alpaca.markets"

#: Retained audit classification; the strict origin parser selects the mode.
LIVE_HOSTS = frozenset({"api.alpaca.markets"})

#: THE ALLOWLIST, and the actual gate. `LIVE_HOSTS` above answers "is this the
#: one host we happen to know reaches real money" — which is a DENYLIST, and a
#: denylist's failure mode is everything nobody thought of:
#:
#:     https://api.alpaca.markets.evil.example/   not in LIVE_HOSTS -> allowed
#:     http://paper-api.alpaca.markets/           cleartext key     -> allowed
#:     https://10.0.0.5:8080/                     a proxy to live   -> allowed
#:     https://paper-api.alpaca.markets@evil/     hostname is evil  -> allowed
#:
#: None of those are hypothetical failures of judgement; they are what "permit
#: everything except one string" means. The gate is inverted: permit exactly
#: the known paper endpoint and refuse every other thing.
#:
#: This is not about paper trading being risky. It is that the eventual move
#: from "paper certified" to anything involving money must require an explicit
#: architectural change, not an environment variable.
PAPER_HOSTS = frozenset({"paper-api.alpaca.markets"})

#: Where the retained JSONL ownership audit lives. Canonical ownership authority
#: is the PostgreSQL account binding; losing this audit file cannot re-arm
#: migration because ordinary startup contains no legacy liquidation path.
DEFAULT_STATE_DIR = "/var/lib/sentinel"


class LiveEndpointRefused(RuntimeError):
    """An origin is invalid or an explicitly PAPER-only operation selected LIVE."""


def trading_endpoint(url: str) -> TradingEndpoint:
    """Validate one canonical trading origin without granting broker authority."""
    try:
        return TradingEndpoint.parse(url)
    except TradingEndpointRefused as exc:
        # Do not echo malformed userinfo, which could contain credentials.
        raise LiveEndpointRefused(
            "ALPACA_BASE_URL must be an exact supported Alpaca HTTPS trading origin") from exc


def is_paper_url(url: str) -> bool:
    """The allowlist predicate, as a FUNCTION on a bare string.

    Split out of `SentinelConfig` because the execution adapter takes a
    `base_url` argument directly and has no config object to ask. Two copies of
    an allowlist drift, and the copy that drifts is the one nobody is reading
    when it matters — so both boundaries call this.
    """
    try:
        return TradingEndpoint.parse(url).environment is TradingEnvironment.PAPER
    except TradingEndpointRefused:
        return False


def assert_paper_url(url: str) -> None:
    """Refuse anything that is not exactly the Alpaca paper endpoint."""
    if is_paper_url(url):
        return
    raise LiveEndpointRefused(
        f"{url!r} is not the Alpaca paper endpoint. Sentinel permits exactly "
        f"https://{sorted(PAPER_HOSTS)[0]} — https scheme, that hostname, no "
        f"embedded credentials. This is an ALLOWLIST on purpose: a rule that "
        f"merely excludes the known live host permits every proxy, lookalike "
        f"domain and cleartext URL nobody thought to enumerate. This operation "
        f"is explicitly PAPER-only.")


class MissingCredentials(RuntimeError):
    """Raised when Alpaca credentials are absent or placeholders."""


@dataclass(frozen=True)
class SentinelConfig:
    alpaca_key: str
    alpaca_secret: str
    base_url: str
    state_dir: Path
    max_cycles: int
    poll_seconds: float
    database_url: str = ""

    @property
    def trading_endpoint(self) -> TradingEndpoint:
        return trading_endpoint(self.base_url)

    @property
    def environment(self) -> TradingEnvironment:
        return self.trading_endpoint.environment

    @property
    def broker_namespace(self) -> str:
        return self.trading_endpoint.broker_namespace

    @property
    def ownership_log(self) -> Path:
        return self.state_dir / "ownership.jsonl"

    @property
    def endpoint_host(self) -> str:
        """The hostname, NORMALISED, so the allowlist compares like with like.

        `urlparse().hostname` already lowercases and strips the port, but not a
        trailing DNS root dot: `paper-api.alpaca.markets.` resolves to exactly
        the same host and is a different string. Stripped here rather than at
        the comparison, so every reader of this property gets the same answer.
        """
        host = (urlparse(self.base_url).hostname or "").lower()
        return host.rstrip(".")

    @property
    def is_live_endpoint(self) -> bool:
        """Kept for the panel and the audit record; NOT the safety gate.

        A denylist answers "is this the one host we know about", which is a
        different question from "is this allowed"."""
        return self.endpoint_host in LIVE_HOSTS

    @property
    def is_paper_endpoint(self) -> bool:
        """The gate. Scheme AND host AND no embedded credentials.

        The scheme matters because `http://` to the paper host is still a
        cleartext API key on the wire, and the userinfo check because
        `https://paper-api.alpaca.markets@evil.example/` has hostname
        `evil.example` — reading the string left to right, a human sees the
        paper host first.
        """
        return is_paper_url(self.base_url)

    def redacted(self) -> dict:
        """Safe to log. The key is shown by LENGTH and last four only — enough to
        tell two accounts apart, not enough to use."""
        tail = self.alpaca_key[-4:] if len(self.alpaca_key) > 4 else ""
        return {
            "base_url": self.base_url,
            "endpoint_host": self.endpoint_host,
            "environment": self.environment.value,
            "broker_namespace": self.broker_namespace,
            "alpaca_key": f"<{len(self.alpaca_key)} chars ...{tail}>",
            "alpaca_secret": "<set>" if self.alpaca_secret else "<unset>",
            "state_dir": str(self.state_dir),
            "ownership_log": str(self.ownership_log),
            "max_cycles": self.max_cycles,
            "poll_seconds": self.poll_seconds,
            # The DSN carries a password. Only presence is reported.
            "database_url": "<set>" if self.database_url else "<unset>",
        }

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SentinelConfig":
        e = os.environ if env is None else env
        endpoint = trading_endpoint(
            e.get("ALPACA_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL)
        cfg = cls(
            alpaca_key=e.get("ALPACA_API_KEY", "").strip(),
            alpaca_secret=e.get("ALPACA_SECRET_KEY", "").strip(),
            base_url=endpoint.base_url,
            state_dir=Path(e.get("SENTINEL_STATE_DIR", DEFAULT_STATE_DIR)),
            max_cycles=int(e.get("SENTINEL_MAX_CYCLES", "40")),
            poll_seconds=float(e.get("SENTINEL_POLL_SECONDS", "5")),
            database_url=e.get("SENTINEL_DATABASE_URL", "").strip(),
        )
        return cfg

    def assert_paper(self) -> None:
        """ALLOWLIST. The endpoint must BE the paper endpoint, not merely fail
        to be the one live host anybody listed."""
        if self.is_paper_endpoint:
            return
        if self.is_live_endpoint:
            why = (f"points at {self.endpoint_host}, the REAL trading API")
        else:
            why = (f"is {self.base_url!r}, which is not the Alpaca paper "
                   f"endpoint. Sentinel permits exactly "
                   f"https://{sorted(PAPER_HOSTS)[0]} — an https scheme, that "
                   f"hostname, and no embedded credentials — because a rule "
                   f"that merely excludes the live host permits every proxy, "
                   f"lookalike domain and cleartext URL nobody enumerated")
        raise LiveEndpointRefused(
            f"ALPACA_BASE_URL {why}. This operation is PAPER-only. "
            f"Use {DEFAULT_BASE_URL}; selecting LIVE cannot grant a PAPER "
            f"administrative operation permission to contact real money."
        )

    def assert_credentials(self) -> None:
        """Checked separately from `assert_paper`, and only by commands that
        actually talk to the broker — so `status` still works on a box with no
        credentials, which is exactly when someone is trying to diagnose one."""
        if not self.alpaca_key or self.alpaca_key == "demo" or not self.alpaca_secret:
            raise MissingCredentials(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY are unset or placeholders. "
                "Sentinel refuses to run a liquidation it cannot verify against "
                "the account: with no credentials every read returns empty, and "
                "an empty account reads as ALREADY FLAT — which would record "
                "ownership over a book it never saw."
            )


def build_broker(config: SentinelConfig):
    """Construct the Alpaca-backed `SentinelBroker` for this configuration."""
    from stock_strategy_shared.broker.alpaca import AlpacaBrokerAdapter

    from sentinel.broker import AlpacaSentinelBroker

    config.assert_paper()
    return AlpacaSentinelBroker(
        AlpacaBrokerAdapter(
            api_key=config.alpaca_key,
            secret_key=config.alpaca_secret,
            base_url=config.base_url,
        )
    )


def build_execution_broker(config: SentinelConfig, *, resolve_security_id,
                           to_broker_symbol=None, live_admission=None):
    """Construct the selected transport with independent LIVE admission.

    Production order transport is addressed by Alpaca's stable ``asset_id``.
    The Trading API accepts an asset ID in its create-order ``symbol`` field,
    so the adapter does not need to send a mutable ticker after resolving a
    permanent listing identity.

    Kept separate from :func:`build_broker`: the latter is the narrow,
    administrative migration seam with broker-native close operations. The
    autonomous executor must never acquire those operations by convenience.
    """
    from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
    from sentinel.execution.certification import (
        certify_adapter, require_certified)

    endpoint = config.trading_endpoint
    if endpoint.environment is TradingEnvironment.LIVE:
        if live_admission is None:
            raise LiveEndpointRefused(
                "LIVE execution requires separately validated account authority and qualification")
        from sentinel.authority.live import require_live_adapter_admission
        require_live_adapter_admission(live_admission, base_url=endpoint.base_url)
    elif live_admission is not None:
        raise LiveEndpointRefused("LIVE admission cannot authorize PAPER transport")
    config.assert_credentials()
    if endpoint.environment is TradingEnvironment.PAPER:
        require_certified("alpaca")
    provider = getattr(resolve_security_id, "source_provider", "SHARADAR")
    if provider not in {"SHARADAR", "ALPACA_NASDAQ", "ALPACA_OPENFIGI"}:
        raise ValueError("execution resolver has an unsupported source symbol domain")
    from_broker_symbol = None
    if provider != "SHARADAR":
        if to_broker_symbol is not None:
            raise ValueError("native source symbols cannot use a legacy symbol override")
        to_broker_symbol = str
        from_broker_symbol = str
    broker = AssetIdAlpacaExecutionBroker(
        api_key=config.alpaca_key, secret_key=config.alpaca_secret,
        base_url=config.base_url, resolve_security_id=resolve_security_id,
        to_broker_symbol=to_broker_symbol,
        from_broker_symbol=from_broker_symbol,
        **({"live_admission": live_admission} if live_admission is not None else {}))
    certify_adapter(broker, name=endpoint.broker_namespace,
                    mode=endpoint.environment.value,
                    **({"live_admission": live_admission} if live_admission is not None else {}))
    from sentinel.execution.contract import resolved_capability_graph
    resolved_capability_graph(broker)
    return broker
