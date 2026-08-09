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

#: Where the ownership log lives. A VOLUME on the NAS, never inside the image:
#: losing it means a restart re-enters legacy cleanup against a Sentinel-owned
#: book. It is the most safety-critical byte Sentinel writes.
DEFAULT_STATE_DIR = "/var/lib/sentinel"


class LiveEndpointRefused(RuntimeError):
    """Raised when configuration points at the real broker."""


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

    @property
    def ownership_log(self) -> Path:
        return self.state_dir / "ownership.jsonl"

    @property
    def endpoint_host(self) -> str:
        return (urlparse(self.base_url).hostname or "").lower()

    @property
    def is_live_endpoint(self) -> bool:
        return self.endpoint_host in LIVE_HOSTS

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
        )
        cfg.assert_paper()
        return cfg

    def assert_paper(self) -> None:
        if self.is_live_endpoint:
            raise LiveEndpointRefused(
                f"ALPACA_BASE_URL points at {self.endpoint_host}, the REAL "
                f"trading API. Sentinel is paper-only and will not start. There "
                f"is deliberately no override: this deployment has no live "
                f"mandate, and an env var that could grant one is the same slip "
                f"the hardcoded trade_type was. Use {DEFAULT_BASE_URL}."
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
