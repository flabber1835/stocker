"""/health is a LIVENESS probe: it must answer without touching the network.

The bug: /health awaited provider.health_check() for every registered provider.
The Ollama provider is registered unconditionally, but `ollama` lives behind
--profile ollama and normally does not exist, so the probe made a real call to an
unresolvable host with a 5.0s inner timeout — the same 5s the compose healthcheck
allows. On a cold `up` the lookup could take that long, five expiries marked the
container unhealthy, llm-vetter's `service_healthy` gate failed, and the whole
live stack exited rc=1. A second `up -d` "fixed" it because DNS was warm by then.

The endpoint always returned {"status": "ok"}. It was never wrong, only slow. So
these tests assert LATENCY and ISOLATION, not the response body.
"""
import asyncio
import os as _os
import sys
import time

import pytest
from fastapi.testclient import TestClient

_GW_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..",
                                          "services", "llm-gateway"))
_app = sys.modules.get("app")
if _app is None or _GW_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]
    if _GW_PATH not in sys.path:
        sys.path.insert(0, _GW_PATH)

import app.main as gw  # noqa: E402


class _HangingProvider:
    """Stands in for Ollama-behind-an-unresolvable-hostname: a health_check that
    blocks for longer than the container healthcheck's entire budget."""

    name = "hanging"
    default_model = "nope"

    def __init__(self, delay: float = 30.0) -> None:
        self.delay = delay
        self.calls = 0

    async def health_check(self) -> bool:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return False


class _ExplodingProvider:
    name = "exploding"
    default_model = "boom"

    async def health_check(self) -> bool:
        raise RuntimeError("host unreachable")


@pytest.fixture
def client():
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture
def hanging(monkeypatch):
    p = _HangingProvider()
    monkeypatch.setattr(gw, "_providers", {"hanging": p})
    return p


# ── the regression ──────────────────────────────────────────────────────────

def test_health_does_not_wait_on_a_hanging_provider(client, hanging):
    """THE fix. With the old code this took 30s; the compose healthcheck allows
    5s, so the container went unhealthy and failed the deploy."""
    t0 = time.monotonic()
    r = client.get("/health")
    elapsed = time.monotonic() - t0
    assert r.status_code == 200
    assert elapsed < 1.0, f"/health took {elapsed:.2f}s — it is doing I/O again"


def test_health_never_calls_a_provider_at_all(client, hanging):
    """Latency alone could pass by accident (a fast local stub). This asserts the
    stronger property: no provider is consulted, so no network is involved
    regardless of how quick that network happens to be today."""
    client.get("/health")
    assert hanging.calls == 0


def test_health_survives_a_provider_that_raises(client, monkeypatch):
    monkeypatch.setattr(gw, "_providers", {"exploding": _ExplodingProvider()})
    assert client.get("/health").status_code == 200


def test_health_works_with_no_providers_registered(client, monkeypatch):
    """The no-ANTHROPIC_API_KEY, no-ollama deploy. Liveness is still liveness."""
    monkeypatch.setattr(gw, "_providers", {})
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


# ── the response contract ───────────────────────────────────────────────────

def test_health_reports_configured_providers_without_probing_them(client, hanging):
    """Which providers are CONFIGURED is process-local state and free. Whether
    each one ANSWERS is a network question, and belongs elsewhere."""
    body = client.get("/health").json()
    assert body["configured_providers"] == ["hanging"]
    assert "providers" not in body, (
        "the probed 'providers' list must live on /health/providers — leaving it "
        "here invites the I/O back")
    assert hanging.calls == 0


def test_health_still_names_the_service_and_default_provider(client, hanging):
    body = client.get("/health").json()
    assert body["service"] == "llm-gateway"
    assert "default_provider" in body


# ── readiness lives on its own endpoint ─────────────────────────────────────

def test_readiness_endpoint_does_probe_the_providers(client, monkeypatch):
    p = _HangingProvider(delay=0.0)
    monkeypatch.setattr(gw, "_providers", {"hanging": p})
    body = client.get("/health/providers").json()
    assert p.calls == 1
    assert body["providers"] == [
        {"name": "hanging", "available": False, "default_model": "nope"}]


def test_readiness_reports_a_raising_provider_as_unavailable(client, monkeypatch):
    monkeypatch.setattr(gw, "_providers", {"exploding": _ExplodingProvider()})
    body = client.get("/health/providers").json()
    assert body["providers"][0]["available"] is False


def test_readiness_is_not_the_healthcheck_target():
    """Guards the whole point: if compose ever probes /health/providers, the
    original failure returns wholesale."""
    import re
    root = _os.path.join(_os.path.dirname(__file__), "..", "..")
    with open(_os.path.join(root, "docker-compose.yml")) as f:
        compose = f.read()
    assert "/health/providers" not in compose
    # and every healthcheck still targets the plain liveness path
    assert re.search(r"urlopen\('http://127\.0\.0\.1:8000/health'\)", compose)
