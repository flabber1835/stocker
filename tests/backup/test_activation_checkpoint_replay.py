"""One real base plus later archived plan/control commits, restored with PG."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

import psycopg

from tests.support.postgres import _EphemeralPostgres, _find_pg_bin, _as_pg_user, _run
from sentinel import schema
from sentinel.feed import store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import sentinel_activation_checkpoint as checkpoint


def test_post_base_activation_state_recovers_through_actual_committed_barrier():
    primary, restored = _EphemeralPostgres(), _EphemeralPostgres()
    base = Path(tempfile.mkdtemp(prefix='sentinel_checkpoint_base_', dir=Path(primary.datadir).parent))
    try:
        primary.start()
        primary.enable_archive()
        with psycopg.connect(primary.sync_dsn) as conn:
            schema.ensure_schema(conn)
            store.migrate_schema(conn)
            conn.execute('CREATE TABLE sentinel_backup_recovery_markers '
                         '(marker text primary key, created_at timestamptz default now())')
            assert conn.execute('SELECT enabled,kill_switch_engaged FROM sentinel_automation_control').fetchone() == (False,True)
            conn.commit()
        if os.geteuid() == 0:
            shutil.chown(base, user='postgres', group='postgres')
        result = _run(_as_pg_user([_find_pg_bin('pg_basebackup'), '-h','127.0.0.1',
            '-p',str(primary.port),'-U',primary.user,'-D',str(base),'-Fp','-Xs','-c','fast']))
        assert result.returncode == 0, result.stderr
        # These rows did not exist in the sole base. There is no second base.
        with psycopg.connect(primary.sync_dsn) as conn:
            conn.execute("INSERT INTO sentinel_execution_plans "
                "(plan_id,decision_session,effective_session,target_exposure,rollout_mode,rollout_version) "
                "VALUES ('Wednesday-plan','2026-10-13','2026-10-14',1,'PINNED_1_00',1)")
            conn.execute("UPDATE sentinel_automation_control SET enabled=true,generation=2,"
                "deployment_id='fixture',broker='alpaca',broker_account_id='PAPER',takeover_epoch=1,"
                "certificate_sha256=%s,rollout_mode='PINNED_1_00',rollout_version=1,config_sha256=%s",
                ('a'*64,'b'*64))
            conn.commit()
        def sql_boundary(argv, **kwargs):
            assert 'psql' in argv
            # Every command is a separate committed session, just like psql.
            with psycopg.connect(primary.sync_dsn, autocommit=True) as conn:
                row = conn.execute(argv[-1]).fetchone()
                return json.dumps(row[0]) if isinstance(row[0],dict) else str(row[0])
        marker, barrier = checkpoint.commit_boundary(sql_boundary)
        archive = Path(primary.datadir) / 'worker-archive'
        with psycopg.connect(primary.sync_dsn, autocommit=True) as conn:
            conn.execute('SELECT pg_switch_wal()')
        deadline = time.monotonic() + 15
        while not (archive / barrier['wal']).is_file() and time.monotonic() < deadline:
            time.sleep(.1)
        assert (archive / barrier['wal']).is_file()
        target = Path(restored.datadir)
        shutil.copytree(base,target,dirs_exist_ok=True)
        with (target / 'postgresql.auto.conf').open('a') as stream:
            stream.write("\nrestore_command='cp " + str(archive) + "/%f %p'\n")
            stream.write("recovery_target_lsn='" + barrier['lsn'] + "'\nrecovery_target_action='pause'\n")
        (target / 'recovery.signal').touch()
        if os.geteuid() == 0:
            for item in [target, *target.rglob('*')]:
                shutil.chown(item,user='postgres',group='postgres')
        result = _run(_as_pg_user([_find_pg_bin('pg_ctl'),'-D',str(target),
            '-o',f'-p {restored.port} -h 127.0.0.1 -k {target}',
            '-l',str(target/'restored.log'),'-w','-t','30','start']))
        assert result.returncode == 0, result.stderr
        restored._started = True
        with psycopg.connect(restored.sync_dsn, autocommit=True) as conn:
            deadline = time.monotonic() + 15
            while not conn.execute('SELECT pg_is_wal_replay_paused()').fetchone()[0]:
                assert time.monotonic() < deadline
                time.sleep(.1)
            assert conn.execute('SELECT pg_is_in_recovery()').fetchone()[0]
            assert conn.execute('SELECT marker FROM sentinel_backup_recovery_markers WHERE marker=%s',
                                (marker,)).fetchone() == (marker,)
            assert conn.execute('SELECT decision_session::text,effective_session::text '
                                'FROM sentinel_execution_plans WHERE plan_id=%s',
                                ('Wednesday-plan',)).fetchone() == ('2026-10-13','2026-10-14')
            assert conn.execute('SELECT enabled,kill_switch_engaged,generation '
                                'FROM sentinel_automation_control').fetchone() == (True,True,2)
    finally:
        restored.stop()
        primary.stop()
        assert base.name.startswith('sentinel_checkpoint_base_') and base.parent == Path(primary.datadir).parent
        shutil.rmtree(base)
