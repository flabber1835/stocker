"""Durable browser succession and result fencing; no network operations."""
from dataclasses import dataclass
from datetime import datetime


def lock(cur) -> None:
    cur.execute("SELECT id FROM sentinel_notification_policy WHERE id=1 FOR UPDATE")
    if cur.fetchone() is None:
        raise RuntimeError("Web Push notification policy singleton is absent")


@dataclass(frozen=True)
class Recipient:
    subscription_id: str
    endpoint: str
    p256dh: str
    auth: str
    retired_at: datetime | None
    refreshed_at: datetime
    eligible_from: datetime


def resolve(cur, subscription_id: str, *, created_at: datetime) -> Recipient | None:
    seen = set()
    while subscription_id not in seen:
        seen.add(subscription_id)
        cur.execute(
            "SELECT subscription_id,endpoint,p256dh,auth,retired_at,"
            " refreshed_at,eligible_from,successor_id,retire_reason"
            " FROM sentinel_web_push_subscriptions WHERE subscription_id=%s",
            (subscription_id,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Web Push recipient succession is missing")
        recipient = Recipient(*row[:7])
        if recipient.eligible_from > created_at:
            # A new enrollment at a reused endpoint has no old obligations.
            return None
        successor, reason = row[7:]
        if successor is None:
            return recipient
        if recipient.retired_at is None or reason != "replaced by browser":
            raise RuntimeError("Web Push recipient succession is inconsistent")
        subscription_id = successor
    raise RuntimeError("Web Push recipient succession is cyclic")
