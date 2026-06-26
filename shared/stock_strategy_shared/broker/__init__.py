"""Broker abstraction — one active broker per deployment (see base.py)."""
from __future__ import annotations

from .alpaca import AlpacaBrokerAdapter
from .base import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerOrder,
    BrokerPosition,
)
from .factory import get_broker_adapter

# Single source of the "position already flat" sentinel that close_position
# returns — trade-executor imports this instead of redefining the literal.
ALREADY_CLOSED_STATUS = BrokerAdapter.ALREADY_CLOSED_STATUS

__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerOrder",
    "BrokerPosition",
    "AlpacaBrokerAdapter",
    "get_broker_adapter",
    "ALREADY_CLOSED_STATUS",
]
