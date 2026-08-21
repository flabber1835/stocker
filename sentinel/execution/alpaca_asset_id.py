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
    AlpacaCredentialsRefused,
    AlpacaExecutionBroker,
    IncompleteBrokerPayload,
    MalformedBrokerPayload,
    RetryableCommandOutcome,
    _retry_after_seconds,
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
            return CommandOutcome(
                state=S.ACKNOWLEDGED,
                broker_order_id=order.broker_order_id,
                detail="accepted; lifecycle reconciles separately",
            )

        if resp.status_code in (401, 403):
            raise AlpacaCredentialsRefused(
                "Alpaca submit authority refused with HTTP "
                f"{resp.status_code}: {(resp.text or '')[:500]}"
            )
        if resp.status_code == 429:
            retry_after = _retry_after_seconds(resp)
            return RetryableCommandOutcome(
                state=S.UNKNOWN,
                retry_after_seconds=retry_after,
                detail=(
                    "HTTP 429 rate limit; same-key retry eligible after "
                    f"{retry_after}s"
                ),
            )
        if resp.status_code == 408:
            return CommandOutcome(
                state=S.UNKNOWN,
                detail="HTTP 408 transport ambiguity",
            )
        if resp.status_code == 422:
            text = (resp.text or "")[:500]
            if "client_order_id" in text or "duplicate" in text.lower():
                return CommandOutcome(
                    state=S.UNKNOWN,
                    detail=f"duplicate key at broker: {text}",
                )
            return CommandOutcome(state=S.REJECTED, detail=text)
        if 400 <= resp.status_code < 500:
            return CommandOutcome(
                state=S.REJECTED,
                detail=(
                    f"HTTP {resp.status_code}: {(resp.text or '')[:500]}"
                ),
            )
        return CommandOutcome(
            state=S.UNKNOWN,
            detail=f"HTTP {resp.status_code}",
        )


__all__ = ["AssetIdAlpacaExecutionBroker"]
