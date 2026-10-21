"""Current scheduled readiness is distinct from future mirror verification."""
import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
import time
from types import SimpleNamespace

import pytest

from sentinel.automation import health
from sentinel.execution import journal
from sentinel.execution.plan import ExecutionPlan
from sentinel.panel import authority_reader, model, sources, verification_monitor

NOW = datetime(2026, 10, 21, 13, 30, tzinfo=timezone.utc)
EXECUTE = NOW + timedelta(minutes=1)
CERTIFICATE = "a" * 64


class Connection:
    def __init__(self, binding=(CERTIFICATE, False, True)):
        self.binding = binding
        self.statements = []
        self.closed = False
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, query, params=None):
        self.statements.append((query, params))
    def fetchone(self):
        return self.binding
    def rollback(self):
        pass
    def close(self):
        self.closed = True


@pytest.fixture
def ready(monkeypatch):
    plan = ExecutionPlan(plan_id="current-plan", decision_session=date(2026, 10, 20),
        effective_session=date(2026, 10, 21), target_exposure=Decimal("1"), data_version=7,
        rollout_mode="CONTROLLER", rollout_version=4, rollout_certificate_sha256=CERTIFICATE)
    cycle = dict(cycle_id="current-cycle", state="WAITING_OPEN", execute_at=EXECUTE,
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        decision_session="2026-10-20", effective_session="2026-10-21")
    current = SimpleNamespace(healthy=True, operational_ready=True, enabled=True,
        kill_switch_engaged=False, policy_state="LEADER_ACTIVE", authority_verdict="PASS",
        authority_lifecycle_current=True, broker_outcome_unresolved=0,
        latest_cycle_id=cycle["cycle_id"], latest_cycle_state="WAITING_OPEN",
        certificate_sha256=CERTIFICATE, rollout_mode="CONTROLLER", rollout_version=4,
        control_generation=12)
    rollout = dict(mode="CONTROLLER", version=4, certificate_sha256=CERTIFICATE)
    monkeypatch.setattr(health, "read_health", lambda conn: current)
    monkeypatch.setattr(journal, "latest_plan", lambda conn: plan)
    monkeypatch.setattr(sources, "_rollout_state", lambda conn: rollout)
    return SimpleNamespace(plan=plan, cycle=cycle, health=current, rollout=rollout,
        publication=SimpleNamespace(version=7), connection=Connection())


def scheduled(ready, *, now=NOW):
    return sources._scheduled_preopen_mirror(ready.connection, ready.cycle,
        ready.publication, "2026-10-20", now=now)


def test_ready_preopen_is_green_but_never_claims_mirror_clean(ready):
    row = scheduled(ready)
    assert row.status == model.OK and "SCHEDULED" in row.value
    assert "NOT VERIFIED" in row.value and "PENDING" in row.value
    assert "CLEAN" not in row.value and row.required_current
    assert model.Panel(rows=[row], now=NOW).operational == model.OK
    assert row.effective_status(EXECUTE) == model.FAIL
    assert row.effective_status(EXECUTE + timedelta(seconds=1)) == model.FAIL
    # A scheduled mirror never conceals another required failure.
    assert model.Panel(rows=[row, model.Row("authority", "Authority", "bad", model.FAIL)], now=NOW).operational == model.FAIL


@pytest.mark.parametrize("field,value", [
    ("state", "PLAN_READY"), ("state", "EXECUTING"), ("state", "BLOCKED"),
    ("execute_at", NOW), ("execute_at", NOW-timedelta(seconds=1)),
    ("failure_code", "BLOCKED"), ("failure_detail", "failure"), ("terminal_reason", "operator"),
    ("cycle_id", "historical-cycle"), ("plan_id", "old-plan"),
    ("plan_fingerprint", "b"*64), ("decision_session", "2026-10-19"),
    ("effective_session", "2026-10-22"),
])
def test_not_ready_or_different_cycle_cannot_be_scheduled(ready, field, value):
    ready.cycle[field] = value
    assert scheduled(ready) is None


@pytest.mark.parametrize("field,value", [
    ("healthy", False), ("operational_ready", False), ("enabled", False),
    ("kill_switch_engaged", True), ("policy_state", "SCHEDULER_STALLED"),
    ("authority_verdict", "FAIL"), ("authority_lifecycle_current", False),
    ("broker_outcome_unresolved", 1), ("latest_cycle_state", "BLOCKED"),
    ("certificate_sha256", "b"*64), ("rollout_mode", "PINNED_1_00"), ("rollout_version", 3),
])
def test_current_native_health_is_required(ready, field, value):
    setattr(ready.health, field, value)
    assert scheduled(ready) is None


@pytest.mark.parametrize("binding", [(CERTIFICATE, False, False), (CERTIFICATE, True, True),
    ("b"*64, False, True), None])
def test_current_generation_nonhistorical_certificate_binding_required(ready, binding):
    ready.connection.binding = binding
    assert scheduled(ready) is None


def test_current_publication_and_rollout_required(ready):
    ready.publication.version = 8
    assert scheduled(ready) is None
    ready.publication.version = 7
    ready.rollout["certificate_sha256"] = "b"*64
    assert scheduled(ready) is None


def test_observer_and_cached_reader_preserve_execution_boundary(ready, monkeypatch):
    from sentinel import informational_paper_mirror as mirror
    from sentinel.feed import readers, store
    monkeypatch.setattr(sources, "_informational_mirror_count", lambda conn: 1)
    monkeypatch.setattr(sources, "_latest_automation_cycle", lambda conn: ready.cycle)
    monkeypatch.setattr(readers, "current", lambda conn: ready.publication)
    monkeypatch.setattr(readers, "frontier", lambda *args: "2026-10-20")
    monkeypatch.setattr(mirror, "require_transport_permitted", lambda *args, **kw: {"status": mirror.NO_UNIT_CHANGE})
    monkeypatch.setattr(mirror, "require_current_plan_status", lambda *args, **kw: {"status": mirror.PENDING})
    monkeypatch.setattr(store, "connect", lambda *args, **kw: ready.connection)
    monkeypatch.setattr(authority_reader, "_evidence", lambda *args: "evidence")
    monkeypatch.setattr(authority_reader, "_key", lambda *args: "expected")
    class ClockType(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)
    class Fixed(datetime, metaclass=ClockType):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(sources, "datetime", Fixed)
    monkeypatch.setattr(verification_monitor, "datetime", Fixed)
    answer = verification_monitor.observe_paper("fixture", True, "expected")
    assert answer["rows"][0]["status"] == model.OK
    assert ready.connection.closed
    assert ready.connection.statements[0][0] == "BEGIN TRANSACTION READ ONLY"
    wall = [NOW]
    reader = authority_reader.Reader(runner=lambda *args, **kw: answer,
        evidence_reader=lambda *args: "evidence", wall_clock=lambda: wall[0],
        expected_keys=frozenset({"paper_reconciliation"}))
    try:
        reader.read("fixture")
        deadline = time.monotonic()+3
        while reader.pending is not None and time.monotonic() < deadline:
            reader.read("fixture"); time.sleep(.005)
        rows = reader.read("fixture", allow_start=False)[0]
        assert rows[0].effective_status(NOW) == model.OK
        wall[0] = EXECUTE
        rows = reader.read("fixture", allow_start=False)[0]
        assert rows[0].valid_until == EXECUTE-timedelta(microseconds=1)
        assert rows[0].effective_status(EXECUTE) == model.FAIL
        # Removing the current pending stamp preserves the old warning.
        monkeypatch.setattr(mirror, "require_current_plan_status", lambda *args, **kw: (_ for _ in ()).throw(mirror.InformationalPaperMirrorUnstamped("missing")))
        row = sources._dual_paper_row(ready.connection, informational_paper_mirror=mirror,
            publication=readers, feed_store=store)
        assert row.status == model.WARN and "PENDING" in row.value
    finally:
        if reader.pending is not None:
            reader.pending.join(timeout=2)


def test_removing_generation_guard_breaks_its_falsifier(ready, monkeypatch):
    tree = ast.parse(inspect.getsource(sources._scheduled_preopen_mirror))
    removed = 0
    class Remove(ast.NodeTransformer):
        def visit_If(self, node):
            nonlocal removed
            if ast.unparse(node.test) == "binding != (certificate, False, True)":
                removed += 1
                return None
            return self.generic_visit(node)
    tree = Remove().visit(tree)
    assert removed == 1
    namespace = dict(sources.__dict__)
    exec(compile(ast.fix_missing_locations(tree), "<removed generation guard>", "exec"), namespace)
    monkeypatch.setattr(sources, "_scheduled_preopen_mirror", namespace["_scheduled_preopen_mirror"])
    with pytest.raises(AssertionError):
        test_current_generation_nonhistorical_certificate_binding_required(ready, (CERTIFICATE, False, False))


def test_removing_execution_boundary_breaks_composed_falsifier(ready, monkeypatch):
    tree = ast.parse(inspect.getsource(model.paper_reconciliation_row))
    removed = 0
    class Remove(ast.NodeTransformer):
        def visit_keyword(self, node):
            nonlocal removed
            if node.arg == "valid_until":
                removed += 1
                return None
            return self.generic_visit(node)
    tree = Remove().visit(tree)
    assert removed == 1
    namespace = dict(model.__dict__)
    exec(compile(ast.fix_missing_locations(tree), "<removed execution boundary>", "exec"), namespace)
    monkeypatch.setattr(model, "paper_reconciliation_row", namespace["paper_reconciliation_row"])
    with pytest.raises(AssertionError):
        test_observer_and_cached_reader_preserve_execution_boundary(ready, monkeypatch)


def test_protected_successor_preserves_exact_predecessor_and_financial_sources():
    import hashlib
    import json
    from pathlib import Path
    from sentinel import protected_cohort_upgrade as upgrade
    profile = upgrade.profile()
    predecessor_path = upgrade.PROFILE.with_name("protected-cohort-runtime-preopen-predecessor.json")
    raw = predecessor_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "1b3ee2862a68aff0b426e1127a916eb8f9a0ad5bda3135b06710ca5c73c281c2"
    old = json.loads(raw)
    changed = {name for name, record in profile["files"].items()
               if record["after"] != old["files"][name]["after"]}
    assert changed == {"panel/model.py", "panel/sources.py"}
    for name, record in profile["files"].items():
        actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
        assert record["after"] == actual
        previous = old["files"][name]["after"]
        assert upgrade.source_allowed(name, previous, actual)
        assert not upgrade.source_allowed(name, previous, "0"*64)
