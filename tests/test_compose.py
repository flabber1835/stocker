"""
Validates docker-compose.yml for structural correctness:
- No dependency cycles (compose rejects these with "cycle found")
- Every depends_on target is a defined service
- Every service_healthy dependency has a healthcheck defined
- Health check probes use 127.0.0.1 not localhost (IPv6 fix for Synology NAS)

These checks run in < 1ms and catch issues that are invisible to unit tests
but immediately break `docker compose up`.
"""
import os
import pytest

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

ROOT = os.path.dirname(os.path.dirname(__file__))  # stocker/
COMPOSE_PATH = os.path.join(ROOT, "docker-compose.yml")


@pytest.fixture(scope="module")
def compose():
    if not HAS_YAML:
        pytest.skip("PyYAML not installed")
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def services(compose):
    return compose.get("services", {})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deps(service_def: dict) -> list[str]:
    """Return list of service names this service depends_on."""
    raw = service_def.get("depends_on", {})
    if isinstance(raw, list):
        return raw
    return list(raw.keys())


def _has_healthcheck(service_def: dict) -> bool:
    return "healthcheck" in service_def


def _probe_cmd(service_def: dict) -> str:
    hc = service_def.get("healthcheck", {})
    test = hc.get("test", [])
    return " ".join(test) if isinstance(test, list) else str(test)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestComposeSyntax:
    def test_compose_file_exists(self):
        assert os.path.exists(COMPOSE_PATH), f"docker-compose.yml not found at {COMPOSE_PATH}"

    def test_compose_file_parses(self, compose):
        assert isinstance(compose, dict)
        assert "services" in compose

    def test_services_not_empty(self, services):
        assert len(services) > 0


class TestDependencyCycles:
    """Detect dependency cycles before Docker does."""

    def _build_graph(self, services):
        return {name: set(_deps(svc)) for name, svc in services.items()}

    def _find_cycle(self, graph):
        """DFS-based cycle detection. Returns the cycle path or None."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in graph}
        parent = {}

        def dfs(node):
            color[node] = GRAY
            for neighbor in graph.get(node, set()):
                if neighbor not in graph:
                    continue
                if color[neighbor] == GRAY:
                    # reconstruct cycle
                    cycle = [neighbor, node]
                    cur = node
                    while cur != neighbor and cur in parent:
                        cur = parent[cur]
                        cycle.append(cur)
                    return list(reversed(cycle))
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = dfs(neighbor)
                    if result:
                        return result
            color[node] = BLACK
            return None

        for node in list(graph):
            if color[node] == WHITE:
                result = dfs(node)
                if result:
                    return result
        return None

    def test_no_dependency_cycles(self, services):
        graph = self._build_graph(services)
        cycle = self._find_cycle(graph)
        assert cycle is None, (
            f"Dependency cycle detected in docker-compose.yml: "
            f"{' -> '.join(cycle)}\n"
            f"This causes 'docker compose up' to fail immediately."
        )


class TestDependencyTargets:
    def test_all_depends_on_targets_exist(self, services):
        missing = []
        for name, svc in services.items():
            for dep in _deps(svc):
                if dep not in services:
                    missing.append(f"{name} depends_on {dep!r} which is not defined")
        assert not missing, "\n".join(missing)

    def test_service_healthy_deps_have_healthchecks(self, services):
        """A service with condition: service_healthy must have a healthcheck, otherwise
        it will never become healthy and compose up will stall forever."""
        bad = []
        for name, svc in services.items():
            raw = svc.get("depends_on", {})
            if isinstance(raw, dict):
                for dep, opts in raw.items():
                    if opts.get("condition") == "service_healthy":
                        if not _has_healthcheck(services.get(dep, {})):
                            bad.append(
                                f"{name} waits for {dep} service_healthy "
                                f"but {dep} has no healthcheck"
                            )
        assert not bad, "\n".join(bad)


class TestHealthCheckProbes:
    """Synology NAS has IPv6 disabled. Python resolves 'localhost' to ::1 first,
    which fails with ENETUNREACH. All probes must use 127.0.0.1."""

    def test_no_healthcheck_uses_localhost(self, services):
        bad = []
        for name, svc in services.items():
            cmd = _probe_cmd(svc)
            if "localhost" in cmd:
                bad.append(f"{name}: healthcheck probe uses 'localhost' — use 127.0.0.1 instead")
        assert not bad, "\n".join(bad)

    def test_http_healthchecks_use_ipv4(self, services):
        """Any healthcheck that opens a URL must use 127.0.0.1."""
        bad = []
        for name, svc in services.items():
            cmd = _probe_cmd(svc)
            if "urlopen" in cmd and "127.0.0.1" not in cmd and "localhost" not in cmd:
                bad.append(f"{name}: urlopen healthcheck missing explicit host")
        assert not bad, "\n".join(bad)


class TestCriticalServices:
    """Smoke-check that key services are present and have the expected structure."""

    REQUIRED = ["postgres", "redis", "api", "pipeline", "scheduler",
                "portfolio-builder", "dashboard", "risk-service", "trade-executor"]

    def test_required_services_defined(self, services):
        missing = [s for s in self.REQUIRED if s not in services]
        assert not missing, f"Required services missing from compose: {missing}"

    def test_postgres_has_healthcheck(self, services):
        assert _has_healthcheck(services["postgres"])

    def test_postgres_healthcheck_uses_tcp_not_unix_socket(self, services):
        """pg_isready without -h uses the Unix socket, which is available during
        postgres's init phase while it is still running init.sql.  Docker marks
        postgres as healthy too early, db-migrator starts, connects via TCP and
        gets 'Connection refused'.  The -h 127.0.0.1 flag forces a TCP probe,
        which only succeeds after the init phase is complete and TCP is open."""
        cmd = _probe_cmd(services["postgres"])
        assert "-h 127.0.0.1" in cmd or "-h localhost" in cmd, (
            "postgres healthcheck must use -h 127.0.0.1 (TCP probe). "
            "Without -h, pg_isready uses the Unix socket which passes during init.sql "
            "execution, causing db-migrator to start before TCP is ready."
        )

    def test_redis_has_healthcheck(self, services):
        assert _has_healthcheck(services["redis"])

    def test_trade_executor_depends_on_risk_service(self, services):
        """trade-executor must not start without risk-service — every trade
        goes through a synchronous risk check."""
        deps = _deps(services.get("trade-executor", {}))
        assert "risk-service" in deps, \
            "trade-executor must depend on risk-service"

    def test_api_does_not_depend_on_app_services(self, services):
        """api must only depend on infrastructure (postgres, redis, db-migrator).
        Depending on other app services creates cycles
        (as happened with api -> llm-vetter -> av-ingestor -> api)."""
        allowed = {"postgres", "redis", "db-migrator"}
        api_deps = set(_deps(services.get("api", {})))
        bad = api_deps - allowed
        assert not bad, (
            f"api depends_on non-infrastructure services {bad} — this causes cycles. "
            f"api should only depend on postgres, redis, and db-migrator."
        )

    def test_scheduler_depends_only_on_infrastructure(self, services):
        """The scheduler must depend ONLY on postgres and db-migrator, not on
        av-ingestor / pipeline / portfolio-builder / llm-vetter.

        Design rationale:
          _trigger_step() catches every HTTP error and returns False; the
          supervisor retries on the next tick (SUPERVISOR_INTERVAL_SECS).
          Adding service_healthy deps for those four services creates a
          mandatory serial chain (~5-7 min on a cold NAS) and makes the
          scheduler hostage to optional services like llm-vetter/llm-gateway
          — if the LLM provider is unreachable, the entire scheduler never
          starts.  The scheduler's built-in retry logic is the correct
          resilience mechanism; Docker deps must not duplicate it.

        Regression: this test replaces the previous
        test_scheduler_waits_for_services_it_triggers which required
        service_healthy on all four triggered services.  That design caused
        the 5-7 min cold-boot delay on the Synology NAS.
        """
        scheduler = services.get("scheduler", {})
        raw = scheduler.get("depends_on", {})
        assert isinstance(raw, dict), \
            "scheduler.depends_on must use the long-form dict with conditions"

        # db-migrator must be complete — scheduler writes to scheduler_runs on start
        assert raw.get("db-migrator", {}).get("condition") == "service_completed_successfully", (
            "scheduler must wait for db-migrator to complete — the very first "
            "scheduler_runs INSERT would fail against a schema that isn't current"
        )

        # postgres is a hard infra dep
        assert "postgres" in raw, "scheduler must depend on postgres"

        # The triggered services must NOT be hard deps — they use built-in retry
        forbidden = {"av-ingestor", "pipeline", "portfolio-builder", "llm-vetter"}
        present = forbidden & set(raw.keys())
        assert not present, (
            f"scheduler must NOT depend_on {present} — the scheduler's "
            f"_trigger_step already handles HTTP errors and retries on the "
            f"next supervisor tick.  Docker service_healthy deps for these "
            f"services create a ~5-7 min mandatory chain on a cold NAS start "
            f"and make the scheduler hostage to optional services like llm-vetter."
        )

    def test_dashboard_does_not_depend_on_api(self, services):
        """Dashboard is a static-file server; JS makes API calls from the browser.
        Requiring api:service_healthy before dashboard starts adds a full extra
        chain (postgres → db-migrator → api → dashboard) with no benefit — the
        browser shows errors when API calls fail, which is the correct UX."""
        dashboard_deps = set(_deps(services.get("dashboard", {})))
        assert "api" not in dashboard_deps, (
            "dashboard must not depend_on api — it is a static-file server and "
            "the JS handles API unavailability in the browser.  Adding api as a "
            "dep creates postgres→db-migrator→api→dashboard serial chain."
        )
