"""Cross-service invariant: no `/health` handler performs external I/O.

Every service in this stack declares the SAME container healthcheck — a 5s
timeout, 5 retries past a 20s start_period — and other services gate on the
result. So a `/health` that reaches out to a dependency has two failure modes
that a plain liveness probe does not:

  * it reports someone ELSE'S outage as its own death, and
  * because a dependency's latency is not bounded by anything this process
    controls, it can exceed the probe budget while the service is perfectly fine.

That is not hypothetical. llm-gateway's /health awaited a provider health_check
against `ollama` — a host that does not exist unless --profile ollama is up —
with a 5.0s inner timeout against the healthcheck's own 5s. Cold deploys
intermittently died with "dependency failed to start: container
stocker-llm-gateway-1 is unhealthy → live stack FAILED (rc=1)", and a second
`docker compose up -d` always "fixed" it. llm-vetter had the same bug one level
up, calling the gateway's /health from its own.

This test is the reason a third instance cannot ship. It is deliberately a
STATIC check across every service: a runtime test would have to import each app
(DB engines, strategy configs, network clients at module scope) and would only
cover the services someone remembered to add.

See docs/architecture.md "container healthchecks probe LIVENESS, never
dependencies".
"""
import ast
import os

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVICES = os.path.join(ROOT, "services")

# Names that mean "this handler is talking to something outside the process".
# Substring-matched against the handler's source, so `httpx.AsyncClient(...)`,
# `await client.get(...)` and `engine.connect()` are all caught.
IO_MARKERS = (
    "httpx", "AsyncClient", "requests.", "urllib",
    "engine.connect", "engine.begin", "conn.execute",
    "redis", "aioredis", "socket.",
)


def _service_mains() -> list[tuple[str, str]]:
    out = []
    for name in sorted(os.listdir(SERVICES)):
        main = os.path.join(SERVICES, name, "app", "main.py")
        if os.path.isfile(main):
            out.append((name, main))
    return out


def _health_handlers(src: str) -> list[ast.AST]:
    """Every function decorated with a route whose path is exactly '/health'.

    Keyed on the DECORATOR, not the function name, because the invariant is
    about what the healthcheck probes — a handler could be called anything."""
    found = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            path = next((a.value for a in dec.args
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)),
                        None)
            if path == "/health":
                found.append(node)
    return found


SERVICE_MAINS = _service_mains()


def test_the_scan_actually_finds_services():
    """A silently-empty parametrization would make every assertion below vacuous
    — the failure mode that makes 'all green' meaningless."""
    assert len(SERVICE_MAINS) >= 10, SERVICE_MAINS


@pytest.mark.parametrize("service,path", SERVICE_MAINS,
                         ids=[s for s, _ in SERVICE_MAINS])
def test_health_handler_performs_no_external_io(service, path):
    with open(path) as f:
        src = f.read()
    for node in _health_handlers(src):
        body = ast.get_source_segment(src, node) or ""
        # Strip the docstring: these handlers explain the bug they exist to
        # avoid, and the explanation necessarily names the offending calls.
        doc = ast.get_docstring(node)
        if doc:
            body = body.replace(doc, "")
        hits = [m for m in IO_MARKERS if m in body]
        assert not hits, (
            f"{service} GET /health references {hits} — a container healthcheck "
            f"must probe liveness only. Move the dependency probe to a separate "
            f"endpoint (see llm-gateway /health/providers).")


@pytest.mark.parametrize("service,path", SERVICE_MAINS,
                         ids=[s for s, _ in SERVICE_MAINS])
def test_health_handler_awaits_nothing(service, path):
    """Broader than the marker list and much harder to sneak past: liveness is
    synchronous work, so any await in the handler is suspect regardless of which
    library it came from."""
    with open(path) as f:
        src = f.read()
    for node in _health_handlers(src):
        awaits = [n for n in ast.walk(node) if isinstance(n, ast.Await)]
        assert not awaits, (
            f"{service} GET /health awaits something at line "
            f"{awaits[0].lineno} — liveness probes must not wait on anything.")


def test_every_compose_healthcheck_targets_the_liveness_path():
    """The invariant is only worth anything if compose actually probes /health.
    A healthcheck pointed at a readiness path reintroduces the bug wholesale."""
    import re
    with open(os.path.join(ROOT, "docker-compose.yml")) as f:
        compose = f.read()
    tests = re.findall(r"urlopen\('http://127\.0\.0\.1:\d+(/[^']*)'\)", compose)
    assert tests, "no python-urlopen healthchecks found — did the shape change?"
    bad = sorted({t for t in tests if t != "/health"})
    assert not bad, f"healthcheck(s) probing a non-liveness path: {bad}"
