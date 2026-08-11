"""Broker transport carried forward from Stocker — Alpaca only.

WHAT SURVIVED THE RETIREMENT, and why this package still exists at all:

```text
base.py     the dict/tuple BrokerAdapter surface. Sentinel's MIGRATION uses it
alpaca.py   the proven Alpaca transport behind that surface
```

Sentinel's ordinary execution does NOT go through here. It speaks the typed
contract in `sentinel/execution/contract.py`, whose Alpaca implementation is
`sentinel/execution/alpaca.py`. This older surface remains for exactly one
caller: the one-time account handover (`sentinel/handover.py`), which is an
ADMINISTRATIVE act and is permitted to use `close_position` — see
docs/sentinel-execution-contract.md §4.4.

REMOVED with the rest of the retired runtime:

```text
factory.get_broker_adapter   runtime BROKER-env dispatch. There is one broker
                             per deployment and Sentinel constructs it directly;
                             a dispatcher is how a second one gets selected by
                             accident
ibkr.IBKRBrokerAdapter       prototype speaking this retired surface. It minted
                             a fresh uuid4 per close attempt, reconstructed the
                             session calendar as Mon-Fri 09:30-16:00 with no
                             holidays, and auto-confirmed broker prompts. It is
                             recorded as NOT CERTIFIED in
                             sentinel/execution/certification.py and must be
                             rewritten against the typed contract, not revived
```

Both are recoverable from the `stocker-legacy-2026-08` branch.
"""
from __future__ import annotations

from .alpaca import AlpacaBrokerAdapter
from .base import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerOrder,
    BrokerPosition,
)

#: Single source of the "position already flat" sentinel that `close_position`
#: returns. Still used by the migration path, which is the only caller.
ALREADY_CLOSED_STATUS = BrokerAdapter.ALREADY_CLOSED_STATUS

__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerOrder",
    "BrokerPosition",
    "AlpacaBrokerAdapter",
    "ALREADY_CLOSED_STATUS",
]
