"""Restore-grade DAY-order fence independent of broker enumeration.

A physical restore necessarily starts PostgreSQL.  Sentinel only submits DAY
orders.  If PostgreSQL starts while XNYS is open, an order that existed in the
broker but was absent from the restored database can still be executable for the
rest of that session.  Exposure increases are therefore deferred until a later
session.  A restart before the open is safe: every pre-restart DAY order belongs
to an earlier session and has already expired.

This is intentionally independent of Alpaca's open-order pagination and of WAL
timeline changes.  Either can provide useful evidence; neither is required to
make an unknown predecessor DAY order harmless before re-risking.
"""
from __future__ import annotations

_INSTALLED = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from sentinel.execution import alpaca, executor
    from sentinel.feed import calendar

    if getattr(alpaca, "_POSTMASTER_DAY_FENCE_INSTALLED", False):
        _INSTALLED = True
        return

    current_execute_session = executor.execute_session
    current_restore_reason = alpaca.restore_increase_fence_reason

    def postmaster_day_order_fence_reason(conn, today) -> str:
        try:
            opened, closed = calendar.session_window(today)
        except Exception:
            # Non-session dates are already non-executable at the paper gateway;
            # this fence does not manufacture a calendar answer.
            return ""
        with conn.cursor() as cur:
            cur.execute("SELECT pg_postmaster_start_time()")
            row = cur.fetchone()
        if row is None or row[0] is None:
            return (
                "PostgreSQL start time is unavailable; restore-grade unknown "
                "DAY-order recovery cannot authorize exposure increases")
        started = row[0]
        if started.tzinfo is None:
            return (
                "PostgreSQL start time is timezone-naive; restore-grade unknown "
                "DAY-order recovery cannot authorize exposure increases")
        started = started.astimezone(opened.tzinfo)
        if opened <= started < closed:
            return (
                "PostgreSQL restarted during XNYS session "
                f"{today.isoformat()} at {started.isoformat()}. Exposure "
                "increases wait for a later session so any broker DAY order "
                "missing from a restored journal must have expired")
        return ""

    def combined_restore_reason(conn, deployment, today):
        return (postmaster_day_order_fence_reason(conn, today)
                or current_restore_reason(conn, deployment, today))

    async def execute_session_with_postmaster_fence(*args, **kwargs):
        if args:
            raise TypeError(
                "execute_session postmaster fence requires keyword arguments")
        reason = postmaster_day_order_fence_reason(
            kwargs["conn"], kwargs["today"])
        if reason:
            original_increase_authority = kwargs.get("increase_authority")

            async def fenced_increase_authority(observation):
                if original_increase_authority is not None:
                    await original_increase_authority(observation)
                raise alpaca.RestoreGradeIncreaseDeferred(reason)

            kwargs = dict(kwargs)
            kwargs["increase_authority"] = fenced_increase_authority
        return await current_execute_session(**kwargs)

    executor.execute_session = execute_session_with_postmaster_fence
    alpaca.restore_increase_fence_reason = combined_restore_reason
    alpaca.postmaster_day_order_fence_reason = postmaster_day_order_fence_reason
    alpaca._POSTMASTER_DAY_FENCE_INSTALLED = True
    _INSTALLED = True


__all__ = ["install"]
