"""The selector is published only after the live database accepts the review schema."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import deployment_fence, operational_schema, schema
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import sentinel_installation_phase as install
import sentinel_runtime_selection as selection


@pytest.mark.parametrize('state', ['fenced', 'enabled', 'kill_released', 'lease_held', 'missing_control'])
def test_public_selector_obeys_current_transactional_fence(conn, monkeypatch, tmp_path, state):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'disposable-selector-qualification-'+'x'*32)
    schema.ensure_schema(conn)
    operational_schema.install_quiescent(conn)
    if state == 'enabled':
        conn.execute("UPDATE sentinel_automation_control SET enabled=TRUE, "
            "deployment_id='fixture',broker='alpaca',broker_account_id='paper',takeover_epoch=1,"
            "certificate_sha256=%s,rollout_mode='PAPER_OBSERVATION_ONLY',rollout_version=1,config_sha256=%s",
            ('a'*64, 'b'*64))
    elif state == 'kill_released':
        conn.execute("UPDATE sentinel_automation_control SET kill_switch_engaged=FALSE")
    elif state == 'lease_held':
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='prior-owner',control_generation=1,"
                     "acquired_at=now(),heartbeat_at=now(),expires_at=now()+interval '1 minute'")
    elif state == 'missing_control':
        conn.execute("DELETE FROM sentinel_automation_control WHERE id=1")
    conn.commit()
    monkeypatch.setattr(selection, 'POINTER', tmp_path/'runtime.env')
    old, new = ('sha256:' + char*64 for char in ('1', '2'))
    selection._write_pointer(old)
    monkeypatch.setattr(install.bootstrap.BootstrapDeploy, 'quiesce_backup_and_migrate', lambda _self: None)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)

    def run(argv, **kwargs):
        # The actual installer opens its own connection to the disposable database.
        assert argv[-3:-1] == ['sentinel', '-c'] and kwargs['timeout'] == 150
        exec(compile(argv[-1], '<installer>', 'exec'), {})

    deploy = install.InstallationDeploy(SimpleNamespace(), SimpleNamespace(env={}, run=run), tmp_path)
    deploy.runtime_repo_digest = new
    if state == 'fenced':
        deploy.quiesce_backup_and_migrate()
        assert selection._pointer_digest(selection.POINTER) == new
    else:
        with pytest.raises((deployment_fence.DeploymentFenceRefused, operational_schema.OperationalSchemaRefused)):
            deploy.quiesce_backup_and_migrate()
        assert selection._pointer_digest(selection.POINTER) == old
    present = conn.execute("SELECT to_regclass('public.sentinel_dashboard_review_events') IS NOT NULL").fetchone()[0]
    assert present is (state == 'fenced')
