"""Sentinel's runtime configuration, and the paper-only guard.

Deployment is Alpaca PAPER only (`docs/sentinel-deployment.md` §2). Sentinel
therefore **refuses to start** against the live trading API rather than labelling
its orders "live" and relying on a downstream gate to reject them.

That is a deliberately stronger rule than Stocker's. Stocker derives a
`trade_type` from the endpoint (`trade-executor/app/main.py
trade_type_for_base_url`) and hands it to the risk service, which rejects it
unless `LIVE_TRADING_ENABLED=true` and `PAPER_ONLY=false` — a two-key turn that
exists because the label used to be hardcoded, which made those gates decorative.
Sentinel has no risk service to appeal to and no live mandate at all, so the
correct behaviour is not to run. There is no env var that overrides this; going
live will be a code change, reviewed as one.

Credentials come from the environment only. Nothing here reads or writes a repo
file, and none of these values are ever logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://paper-api.alpaca.markets"

#: Hosts that reach REAL money. Mirrors Stocker's `_LIVE_ALPACA_HOSTS`; kept here
#: rather than imported because Sentinel must not depend on a retired service,
#: and because the two make different DECISIONS from the same fact — Stocker
#: labels, Sentinel refuses.
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
    """Raised when configuration points at anything but the paper broker."""


def is_paper_url(url: str) -> bool:
    """The allowlist predicate, as a FUNCTION on a bare string.

    Split out of `SentinelConfig` because the execution adapter takes a
    `base_url` argument directly and has no config object to ask. Two copies of
    an allowlist drift, and the copy that drifts is the one nobody is reading
    when it matters — so both boundaries call this.
    """
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    return (parsed.scheme == "https"
            and not parsed.username and not parsed.password
            and host in PAPER_HOSTS)


def assert_paper_url(url: str) -> None:
    """Refuse anything that is not exactly the Alpaca paper endpoint."""
    if is_paper_url(url):
        return
    raise LiveEndpointRefused(
        f"{url!r} is not the Alpaca paper endpoint. Sentinel permits exactly "
        f"https://{sorted(PAPER_HOSTS)[0]} — https scheme, that hostname, no "
        f"embedded credentials. This is an ALLOWLIST on purpose: a rule that "
        f"merely excludes the known live host permits every proxy, lookalike "
        f"domain and cleartext URL nobody thought to enumerate. Going live "
        f"must be a reviewed code change, never a URL.")


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
        cfg = cls(
            alpaca_key=e.get("ALPACA_API_KEY", "").strip(),
            alpaca_secret=e.get("ALPACA_SECRET_KEY", "").strip(),
            base_url=e.get("ALPACA_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            state_dir=Path(e.get("SENTINEL_STATE_DIR", DEFAULT_STATE_DIR)),
            max_cycles=int(e.get("SENTINEL_MAX_CYCLES", "40")),
            poll_seconds=float(e.get("SENTINEL_POLL_SECONDS", "5")),
            database_url=e.get("SENTINEL_DATABASE_URL", "").strip(),
        )
        cfg.assert_paper()
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
            f"ALPACA_BASE_URL {why}. Sentinel is paper-only and will not "
            f"start. There is deliberately no override: this deployment has no "
            f"live mandate, and an env var that could grant one is the same "
            f"slip the hardcoded trade_type was. Use {DEFAULT_BASE_URL}."
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
                           to_broker_symbol=None):
    """Construct the certified typed Alpaca PAPER execution adapter.

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

    config.assert_paper()
    config.assert_credentials()
    require_certified("alpaca")
    broker = AssetIdAlpacaExecutionBroker(
        api_key=config.alpaca_key, secret_key=config.alpaca_secret,
        base_url=config.base_url, resolve_security_id=resolve_security_id,
        to_broker_symbol=to_broker_symbol)
    certify_adapter(broker, name="alpaca", mode="ALPACA_PAPER")
    from sentinel.execution.contract import resolved_capability_graph
    resolved_capability_graph(broker)
    return broker
