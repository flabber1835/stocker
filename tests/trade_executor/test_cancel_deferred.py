"""Unit test for /jobs/cancel-deferred — the local-only purge of un-sent
(status='deferred') orders that a freshly-built target supersedes.

Mocks the SQLAlchemy engine (no real Postgres): asserts the endpoint runs an
UPDATE flipping deferred → canceled, returns the rowcount as `cancelled`, and
makes NO Alpaca call (deferred orders were never sent to the broker).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import app.main as ex


class _FakeResult:
    rowcount = 5


def _fake_conn(captured):
    async def _execute(stmt, params=None):
        captured.append(str(stmt))
        return _FakeResult()
    conn = MagicMock()
    conn.execute = _execute
    return conn


def test_cancel_deferred_flips_deferred_to_canceled_and_reports_count():
    captured: list[str] = []
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=_fake_conn(captured))
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(ex, "engine") as eng:
        eng.begin = MagicMock(return_value=cm)
        resp = asyncio.run(ex.cancel_deferred())

    assert resp.status == "ok"
    assert resp.cancelled == 5
    sql = " ".join(captured).lower().replace(" ", "")
    assert "status='canceled'" in sql          # flips to canceled
    assert "wherestatus='deferred'" in sql      # scoped to un-sent deferred rows


def test_cancel_deferred_makes_no_alpaca_call(monkeypatch):
    """Deferred orders never reached the broker — the purge is local-only, so the
    endpoint must not touch Alpaca even if credentials are set."""
    called = {"alpaca": False}

    # Any outbound HTTP would mean a broker call — fail if attempted.
    class _Boom:
        def __init__(self, *a, **k): called["alpaca"] = True
    monkeypatch.setattr(ex.httpx, "AsyncClient", _Boom, raising=False)

    captured: list[str] = []
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=_fake_conn(captured))
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch.object(ex, "engine") as eng:
        eng.begin = MagicMock(return_value=cm)
        asyncio.run(ex.cancel_deferred())

    assert called["alpaca"] is False
