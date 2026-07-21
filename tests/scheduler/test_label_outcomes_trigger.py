"""Daily decision-ledger labeling trigger (_maybe_label_outcomes): best-effort,
once-per-local-day, disableable, and failure never raises into the tick.

Patching note: monkeypatch via the function's __globals__ (the root conftest
re-imports app.main per test, so a string-target patch can hit a different
module instance than the one under test)."""
import asyncio
import types

from app import main


class _FakeResp:
    status_code = 200


def _fake_httpx(calls, fail=False):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **k):
            calls.append(url)
            if fail:
                raise ConnectionError("pipeline down")
            return _FakeResp()

    return types.SimpleNamespace(AsyncClient=_Client)


def _globals():
    g = main._maybe_label_outcomes.__globals__
    assert g is not None
    return g


def test_fires_once_per_day(monkeypatch):
    g = _globals()
    calls = []
    monkeypatch.setitem(g, "httpx", _fake_httpx(calls))
    monkeypatch.setitem(g, "OUTCOME_LABELING_ENABLED", True)
    monkeypatch.setitem(g, "_outcome_labeling_attempted", None)
    asyncio.run(main._maybe_label_outcomes())
    assert len(calls) == 1 and calls[0].endswith("/jobs/label-outcomes")
    asyncio.run(main._maybe_label_outcomes())
    assert len(calls) == 1          # same local day → gated


def test_disabled_flag_suppresses(monkeypatch):
    g = _globals()
    calls = []
    monkeypatch.setitem(g, "httpx", _fake_httpx(calls))
    monkeypatch.setitem(g, "OUTCOME_LABELING_ENABLED", False)
    monkeypatch.setitem(g, "_outcome_labeling_attempted", None)
    asyncio.run(main._maybe_label_outcomes())
    assert calls == []


def test_pipeline_down_never_raises(monkeypatch):
    g = _globals()
    calls = []
    monkeypatch.setitem(g, "httpx", _fake_httpx(calls, fail=True))
    monkeypatch.setitem(g, "OUTCOME_LABELING_ENABLED", True)
    monkeypatch.setitem(g, "_outcome_labeling_attempted", None)
    asyncio.run(main._maybe_label_outcomes())   # must swallow the error
    assert len(calls) == 1
