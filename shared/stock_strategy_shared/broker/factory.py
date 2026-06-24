"""Deploy-time broker selection.

One broker is active per deployment, chosen by the `BROKER` env var (default
`alpaca`). Each machine runs a single book against a single broker; there is no
runtime multi-broker routing. To add IBKR, implement `IBKRBrokerAdapter` and add
a branch here behind `BROKER=ibkr` (+ the `--profile ibkr` session sidecar).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from .alpaca import AlpacaBrokerAdapter
from .base import BrokerAdapter


def get_broker_adapter(
    *,
    http_provider: Optional[Callable[[], object]] = None,
    **kwargs,
) -> BrokerAdapter:
    """Return the adapter for the deployment's active broker.

    `http_provider` lets a service route transport through its own module-level
    `httpx` (so existing test patches keep working) — see base.BrokerAdapter.
    """
    broker = os.getenv("BROKER", "alpaca").strip().lower()
    if broker in ("", "alpaca"):
        return AlpacaBrokerAdapter(http_provider=http_provider, **kwargs)
    raise ValueError(
        f"Unsupported BROKER={broker!r}. Supported: 'alpaca' "
        "(IBKR planned — implement IBKRBrokerAdapter and add a branch here)."
    )
