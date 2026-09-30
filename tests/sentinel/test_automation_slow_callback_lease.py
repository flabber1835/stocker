"""A real callback process may outlive its initial automation leader lease."""
import asyncio
import time

import pytest

from sentinel.automation import store
from sentinel.automation.model import CancellationAuthority, StaleLeaderRefused
from sentinel.feed import store as feed_store
from tests.sentinel.test_issue_201_automation_financial_grade import (
    conn, pg, config, enable, service_for,  # noqa: F401
)


@pytest.mark.asyncio
@pytest.mark.parametrize("steal_fence", [False, True])
async def test_blocking_child_keeps_leadership_only_while_authorized(conn, pg, tmp_path, steal_fence):
    cfg = config(lease_seconds=3, heartbeat_seconds=1, callback_deadline_seconds=15)
    enable(conn, cfg)
    service = service_for(cfg)
    permit = store.acquire_lease(conn, holder_id=service.holder_id, lease_seconds=3)
    marker = tmp_path / "callback-complete"

    class Context:
        def __init__(self):
            self.cancellation = CancellationAuthority()

        def require_active(self):
            self.cancellation.require_active()

    async def slow(context):
        # Deliberately block the child's event loop; renewal belongs to the parent.
        time.sleep(5)
        context.require_active()
        with feed_store.connect(pg.sync_dsn) as independent:
            renewed = store.require_leader(independent, permit)
            assert renewed.expires_at > permit.expires_at
        marker.write_text("completed")
        return {"completed": True}

    async def fence():
        await asyncio.sleep(1.5)
        conn.execute("UPDATE sentinel_automation_lease SET fence_token=fence_token+1 WHERE id=1")
        conn.commit()

    thief = asyncio.create_task(fence()) if steal_fence else None
    try:
        operation = service._invoke(slow, Context(), permit=permit, phase="PREPARE",
            heartbeat_conn_factory=lambda: feed_store.connect(pg.sync_dsn))
        if steal_fence:
            with pytest.raises(StaleLeaderRefused):
                await operation
            assert not marker.exists()
        else:
            assert await operation == {"completed": True}
            assert marker.read_text() == "completed"
    finally:
        if thief is not None:
            await thief
