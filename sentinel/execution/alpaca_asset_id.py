"""Production Alpaca transport that addresses orders by stable asset identity.

Alpaca's create-order API accepts an asset ID in the request field named
``symbol``.  Using the already-resolved durable ``BrokerInstrument.broker_id``
therefore removes the ticker-reuse/relisting race entirely: the transport names
the exact Alpaca asset that Sentinel resolved, rather than resolving a ticker
and later sending that mutable ticker spelling.

This class deliberately subclasses the reviewed Alpaca adapter so observation,
recovery, status mapping, pagination and acknowledgement validation remain one
implementation.  Only the mutation address changes.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from sentinel.execution.alpaca import (
    AlpacaExecutionBroker,
    MalformedBrokerPayload,
)
from sentinel.execution.contract import (
    BrokerInstrument,
    CommandOutcome,
    OrderTerms,
    Side,
)


class AssetIdAlpacaExecutionBroker(AlpacaExecutionBroker):
    """Selected Alpaca transport whose orders are bound to ``asset_id``."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        from sentinel.trading_environment import TradingEnvironment
        if self.environment is TradingEnvironment.PAPER:
            # Current owned-account cash only. The independent fill-interval,
            # historical close and finality capabilities remain quarantined.
            self.capabilities = replace(
                self.capabilities, account_cash_activity_evidence=True)
            self.financial_activity_sse = True

    async def submit(
        self,
        *,
        client_key: str,
        instrument: BrokerInstrument,
        side: Side,
        quantity: Decimal,
        order_terms: OrderTerms = OrderTerms(),
    ) -> CommandOutcome:
        asset_id = str(instrument.broker_id or "").strip()
        if not asset_id:
            raise MalformedBrokerPayload(
                "Alpaca mutation requires the durable broker asset id. The "
                "adapter advertises instrument_identity and may not fall back "
                "to a mutable ticker spelling at the transport boundary."
            )

        return await self._submit_order(symbol=asset_id, client_key=client_key,
            instrument=instrument, side=side, quantity=quantity, order_terms=order_terms)


__all__ = ["AssetIdAlpacaExecutionBroker"]
