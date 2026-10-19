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

from decimal import Decimal

from sentinel.execution.alpaca import (
    AlpacaExecutionBroker,
    IncompleteBrokerPayload,
    MalformedBrokerPayload,
    MalformedOrderTerms,
    _submit_body,
    _submit_error_outcome,
    _submit_outcome,
)
from sentinel.execution.contract import (
    BrokerInstrument,
    CommandOutcome,
    OrderTerms,
    Side,
)
from sentinel.execution.states import CommandState as S


class AssetIdAlpacaExecutionBroker(AlpacaExecutionBroker):
    """Alpaca PAPER adapter whose order transport is bound to ``asset_id``."""

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

        body = _submit_body(symbol=asset_id, client_key=client_key, side=side,
            quantity=quantity, order_terms=order_terms, capabilities=self.capabilities)
        try:
            async with self._httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v2/orders",
                    headers=self._headers(),
                    json=body,
                )
        except Exception as exc:  # noqa: BLE001
            return CommandOutcome(
                state=S.UNKNOWN,
                detail=f"{type(exc).__name__}: {exc}",
            )

        if resp.status_code in (200, 201):
            try:
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                return CommandOutcome(
                    state=S.UNKNOWN,
                    detail=(
                        "2xx response body unreadable: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            try:
                order = self._validate_submit_response(
                    payload,
                    client_key=client_key,
                    instrument=instrument,
                    side=side,
                    quantity=quantity,
                    order_terms=order_terms,
                )
            except (IncompleteBrokerPayload, MalformedOrderTerms) as exc:
                broker_order_id = (
                    str(payload.get("id") or "")
                    if isinstance(payload, dict)
                    else ""
                )
                return CommandOutcome(
                    state=S.UNKNOWN,
                    broker_order_id=broker_order_id or None,
                    detail=f"incomplete 2xx acknowledgement: {exc}",
                )
            return _submit_outcome(order)

        return _submit_error_outcome(resp)


__all__ = ["AssetIdAlpacaExecutionBroker"]
