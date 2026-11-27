"""Offer the cash reader's bounded Alpaca trade publications to its calling reservation."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .alpaca_trade_amendments import active_native_fills


@dataclass(frozen=True)
class TradeWindow:
    account: tuple[str, str, str]
    after: str | None
    cursor: str | None
    through: datetime
    trades: tuple[dict, ...]
    decode: Callable

    def covers(self, activity, observation):
        identity = observation.account_identity
        return (identity is not None and self.account == (identity.broker, identity.account_id, identity.raw.get("id"))
                and activity is not None and (activity.broker, activity.account_id) == self.account[:2]
                and activity.last_event_id == self.cursor and activity.processed_through == self.through
                and self.through >= observation.observed_at)

    def by_order(self, orders):
        by_id = {order.broker_order_id: order.client_key for order in orders}
        selected = {order.client_key: [] for order in orders}
        for row in self.trades:
            details = row["details"]
            key = str(details.get("client_order_id") or "").strip() or None
            native_key = by_id.get(str(details.get("order_id") or "").strip())
            if ((native_key is not None and key is not None and key != native_key)
                    or (key in selected and native_key != key)):
                raise ValueError("trade publication conflicts with its reserved native order identity")
            key = native_key or key
            if key in selected:
                selected[key].append(row)
        return selected

    def fills(self, events):
        return active_native_fills(events, account_uuid=self.account[2], decode_fill=self.decode)


_CAPTURE = ContextVar("sentinel_bounded_trade_window", default=None)


@contextmanager
def capture():
    windows = []
    token = _CAPTURE.set(windows)
    try:
        yield windows
    finally:
        _CAPTURE.reset(token)


def observe(*, batch, after, events, decode):
    windows = _CAPTURE.get()
    if windows is not None and batch.native_account is not None and not batch.trade_amendments:
        # Some native responses include the authenticated cursor anchor itself.
        trades = tuple(row for row in events if row["activity_type"] == "TRD"
                       and (after is None or row["event_id"] > after))
        windows.append(TradeWindow(batch.native_account, after, batch.last_event_id, batch.processed_through,
                                   trades, decode))

