"""The vetter's /health must not call the gateway.

This was the same bug one level up: llm-vetter's container healthcheck made an
HTTP request to llm-gateway's /health, which then probed ollama. A chain of
liveness probes is a chain of shared fate — this container's health depended on a
service (ollama) that is optional in every default deploy, reached through
another service that was itself the thing timing out.

Static assertions rather than a TestClient: importing llm-vetter's app pulls in a
DB engine and strategy config at module scope. The property being protected is
structural — "no network call in this function" — which source inspection
establishes more directly than a mock ever could.
"""
import ast
import inspect
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
MAIN = os.path.join(ROOT, "services", "llm-vetter", "app", "main.py")


@pytest.fixture(scope="module")
def tree():
    with open(MAIN) as f:
        return ast.parse(f.read()), f


def _func(src_tree, name):
    for node in ast.walk(src_tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in llm-vetter/app/main.py")


@pytest.fixture(scope="module")
def src():
    with open(MAIN) as f:
        return f.read()


def test_health_makes_no_http_call(src):
    """THE regression. The healthcheck's target must be I/O-free."""
    node = _func(ast.parse(src), "health")
    body = ast.get_source_segment(src, node)
    for forbidden in ("AsyncClient", "httpx", "LLM_GATEWAY_URL}/health", "await client"):
        assert forbidden not in body, (
            f"llm-vetter /health references {forbidden!r} — it is doing I/O again")


def test_health_has_no_await_at_all(src):
    """Stronger and harder to sneak past: a liveness probe should not await
    anything, whatever library it reaches for."""
    node = _func(ast.parse(src), "health")
    assert not any(isinstance(n, ast.Await) for n in ast.walk(node)), \
        "llm-vetter /health awaits something — liveness must be synchronous work"


def test_the_gateway_probe_still_exists_on_its_own_endpoint(src):
    """The information was useful; only its placement was wrong. Deleting it
    outright would have traded one problem for a blind spot."""
    node = _func(ast.parse(src), "health_gateway")
    body = ast.get_source_segment(src, node)
    assert "LLM_GATEWAY_URL" in body and "AsyncClient" in body
    assert '@app.get("/health/gateway")' in src


def test_health_still_reports_the_local_configuration(src):
    """It remains a useful diagnostic — just one that reads process state rather
    than the network."""
    node = _func(ast.parse(src), "health")
    body = ast.get_source_segment(src, node)
    for key in ("vetter_mode", "drawdown_backstop_pct", "config_hash",
                "llm_enabled"):
        assert key in body, key


# ── the compose edge that turned a slow probe into a failed deploy ──────────

@pytest.fixture(scope="module")
def compose():
    with open(os.path.join(ROOT, "docker-compose.yml")) as f:
        return f.read()


def test_no_service_gates_startup_on_the_gateway_being_healthy(compose):
    """`llm-gateway: condition: service_healthy` is what escalated one slow probe
    into 'live stack FAILED (rc=1)'. The vetter runs drawdown_only by default and
    makes no LLM calls at all, so the coupling bought nothing."""
    blocks = re.findall(r"^\s+llm-gateway:\n\s+condition:\s+(\S+)", compose, re.M)
    assert blocks, "expected at least one depends_on edge on llm-gateway"
    assert all(c == "service_started" for c in blocks), (
        f"a service still gates startup on llm-gateway health: {blocks}")


def test_the_gateway_healthcheck_targets_plain_health(compose):
    """If compose ever probes a readiness path, the original failure returns."""
    gw = compose[compose.index("  llm-gateway:"):]
    gw = gw[:gw.index("\n  portfolio-builder:")]
    assert "127.0.0.1:8000/health'" in gw
    assert "/health/providers" not in gw
