"""Real SQL proof that software fencing is independent of financial coverage."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sentinel import deployment_fence
from sentinel.automation.health import read_health
from sentinel.execution import journal
from sentinel.feed import store
from tests.sentinel.test_execution_evidence_projection import (
    base_conn, conn, pg, bootstrap, install as install_coverage, record,  # noqa: F401
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import sentinel_installation_phase as software


def test_financial_activation_retains_the_original_health_gate(tmp_path):
    obj = software.core.AutonomousDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    obj._installation_only = False
    def refused(argv, **_kwargs):
        assert argv == ['automation-status']
        raise software.core.DeployRefused('EVIDENCE_COVERAGE_BINDING_CHANGED')
    obj._base_cli = refused
    with pytest.raises(software.core.DeployRefused, match='BINDING_CHANGED'):
        obj._automation_status()


def reader(database, monkeypatch, tmp_path, *, remove_fence=False):
    monkeypatch.setenv('SENTINEL_DATABASE_URL', database.info.dsn)
    def run(argv, **kwargs):
        assert '--no-deps' in argv and kwargs['capture'] is True
        code = argv[argv.index('-c') + 1]
        if remove_fence:
            assert code.count('deployment_fence.require(c);') == 1
            code = code.replace('deployment_fence.require(c);', '')
        output = StringIO()
        with redirect_stdout(output):
            exec(compile(code, 'installation-control-reader', 'exec'), {})
        return subprocess.CompletedProcess(argv, 0, output.getvalue(), '')
    obj = software.InstallationDeploy(SimpleNamespace(),
        SimpleNamespace(env={}, run=run), tmp_path)
    return obj._installation_control


def test_post_ddl_coverage_refusal_does_not_block_structural_fence(conn, monkeypatch, tmp_path):
    record(conn)
    install_coverage(conn, monkeypatch)
    bootstrap(conn)
    # A legitimate replacement with the identical reviewed definition advances
    # the DDL epoch without corrupting the schema or any financial row.
    definition = conn.execute("SELECT pg_get_functiondef("
        "'sentinel_backup_progress_guard_v2()'::regprocedure)").fetchone()[0]
    conn.execute(definition)
    conn.commit()
    health = read_health(conn)
    conn.rollback()
    assert health.policy_state == 'UNCERTIFIABLE_OBSERVATIONS'
    assert 'EVIDENCE_COVERAGE_BINDING_CHANGED' in health.reason
    with pytest.raises(journal.ObservationEvidenceUncertifiable, match='BINDING_CHANGED'):
        journal.require_observation_integrity(conn)
    conn.rollback()
    before = conn.execute('SELECT row_to_json(c) FROM sentinel_automation_control c').fetchone()[0]
    conn.rollback()
    proof = reader(conn, monkeypatch, tmp_path)()
    assert proof == dict(enabled=False, kill_switch_engaged=True, control_generation=1)
    assert conn.execute('SELECT row_to_json(c) FROM sentinel_automation_control c').fetchone()[0] == before
    conn.rollback()
    assert not health.operational_ready


@pytest.mark.parametrize('remove_fence', [False, True])
def test_native_fence_refusal_is_preserved_and_removing_it_is_detected(
        conn, monkeypatch, tmp_path, remove_fence):
    def refused(_conn):
        raise deployment_fence.DeploymentFenceRefused('durable kill and invalidated lease required')
    monkeypatch.setattr(deployment_fence, 'require', refused)
    check = reader(conn, monkeypatch, tmp_path, remove_fence=remove_fence)
    if remove_fence:
        # The actual generated child command is mutated and executed: this
        # demonstrates that removing its native guard defeats the regression.
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            with pytest.raises(deployment_fence.DeploymentFenceRefused):
                check()
    else:
        with pytest.raises(deployment_fence.DeploymentFenceRefused):
            check()
