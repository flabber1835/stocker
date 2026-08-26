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
    _submit_error_outcome,
    _submit_outcome,
)
from sentinel.execution.contract import (
    BrokerInstrument,
    CommandOutcome,
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
    ) -> CommandOutcome:
        asset_id = str(instrument.broker_id or "").strip()
        if not asset_id:
            raise MalformedBrokerPayload(
                "Alpaca mutation requires the durable broker asset id. The "
                "adapter advertises instrument_identity and may not fall back "
                "to a mutable ticker spelling at the transport boundary."
            )

        body = {
            # Alpaca documents this request field as accepting either a symbol
            # or an asset ID. Use the stable ID so ticker reuse cannot redirect
            # a previously-authorized command to another listing.
            "symbol": asset_id,
            "qty": str(quantity),
            "side": "buy" if side is Side.BUY else "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_key,
            "order_class": "simple",
            "extended_hours": False,
        }
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
                )
            except IncompleteBrokerPayload as exc:
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
