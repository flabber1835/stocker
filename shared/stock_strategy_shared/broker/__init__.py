"""Broker abstraction — one active broker per deployment (see base.py)."""
from __future__ import annotations

from .alpaca import AlpacaBrokerAdapter
from .base import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
    SubmitResult,
)
from .factory import get_broker_adapter

__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerOrder",
    "BrokerPosition",
    "OrderRequest",
    "SubmitResult",
    "AlpacaBrokerAdapter",
    "get_broker_adapter",
]
