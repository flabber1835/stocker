"""Broker transport carried forward from Stocker — Alpaca only.

WHAT SURVIVED THE RETIREMENT, and why this package still exists at all:

```text
base.py     the dict/tuple BrokerAdapter surface. Sentinel's MIGRATION uses it
alpaca.py   the proven Alpaca transport behind that surface
```

Sentinel's ordinary execution does NOT go through here. It speaks the typed
contract in `sentinel/execution/contract.py`, whose Alpaca implementation is
`sentinel/execution/alpaca.py`. The one-time account handover reuses this older
transport only for complete reads and exact named requests; liquidation itself
is now a durable execution-journal command. The legacy `close_position` and
`cancel_all_orders` methods remain transport compatibility surface, but no
production Sentinel caller may use them.

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

#: Compatibility token returned by the retired broker-native close method.
#: Production Sentinel migration uses named journal commands instead.
ALREADY_CLOSED_STATUS = BrokerAdapter.ALREADY_CLOSED_STATUS

__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerOrder",
    "BrokerPosition",
    "AlpacaBrokerAdapter",
    "ALREADY_CLOSED_STATUS",
]
