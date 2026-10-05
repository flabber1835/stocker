"""Explicit device cancellation of informational tests; never trading alerts."""
from sentinel import push_recipients

ACTOR = "notification-policy"
REASON = "CANCELLED_BY_DEVICE"
# All consumers use alias a. Acknowledgement alone cannot hide real incidents.
CANCELLED_TEST_SQL = (
    "(a.event_type='PUSH_ENROLLMENT_TEST' AND a.severity='INFO'"
    " AND a.state='DEAD_LETTER' AND a.ack_state='ACKNOWLEDGED'"
    " AND a.acknowledged_by='notification-policy'"
    " AND a.acknowledgement='CANCELLED_BY_DEVICE')")


class TestNotificationCancelled(RuntimeError):
    retryable = False


def is_cancelled(alert) -> bool:
    return (alert.event_type == "PUSH_ENROLLMENT_TEST" and alert.severity == "INFO"
            and alert.state == "DEAD_LETTER" and alert.ack_state == "ACKNOWLEDGED"
            and alert.acknowledged_by == ACTOR and alert.acknowledgement == REASON)


def removed_by_device(conn, alert) -> bool:
    if alert.event_type != "PUSH_ENROLLMENT_TEST" or alert.severity != "INFO":
        return False
    target = alert.payload.get("subscription_id")
    if not target:
        return False
    with conn.cursor() as cur:
        push_recipients.lock(cur)
        recipient = push_recipients.resolve(cur, target, created_at=alert.created_at)
        if recipient is None or recipient.retired_at is None:
            return False
        cur.execute("SELECT retire_reason FROM sentinel_web_push_subscriptions"
                    " WHERE subscription_id=%s", (recipient.subscription_id,))
        return cur.fetchone()[0] == "removed by device"


def acknowledge_removed_tests(conn) -> None:
    """Recover historical dead tests, without rewriting delivery or active claims."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT a.alert_id FROM sentinel_alert_outbox a"
            " JOIN sentinel_web_push_subscriptions s"
            " ON s.subscription_id=a.payload->>'subscription_id'"
            " WHERE a.event_type='PUSH_ENROLLMENT_TEST' AND a.severity='INFO'"
            " AND a.state='DEAD_LETTER' AND a.ack_state='UNACKNOWLEDGED'"
            " AND s.retire_reason='removed by device'"
            " AND s.retired_at>=a.created_at ORDER BY a.created_at LIMIT 100"
            " FOR UPDATE OF a")
        for (alert_id,) in cur.fetchall():
            cur.execute(
                "UPDATE sentinel_alert_outbox SET ack_state='ACKNOWLEDGED',"
                " acknowledged_by=%s,acknowledgement=%s,"
                " acknowledged_at=clock_timestamp(),updated_at=clock_timestamp()"
                " WHERE alert_id=%s", (ACTOR, REASON, alert_id))
    conn.commit()
