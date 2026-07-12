"""Deploy-time broker selection.

One broker is active per deployment, chosen by the `BROKER` env var (default
`alpaca`). Each machine runs a single book against a single broker; there is no
runtime multi-broker routing. IBKR is BUILT but DORMANT: activating it requires
BROKER=ibkr AND the `--profile ibkr` session sidecar AND IBKR_* env — the
default deployment never touches it.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from .alpaca import AlpacaBrokerAdapter
from .base import BrokerAdapter
from .ibkr import IBKRBrokerAdapter


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
    if broker == "ibkr":
        return IBKRBrokerAdapter(http_provider=http_provider, **kwargs)
    raise ValueError(
        f"Unsupported BROKER={broker!r}. Supported: 'alpaca', 'ibkr'."
    )
