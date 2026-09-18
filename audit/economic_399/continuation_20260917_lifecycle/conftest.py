from pathlib import Path
import pytest
from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from sentinel import schema, backup_runtime_authority
from sentinel.feed import store as feed_store

@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres()
    server.start()  # Environment failures are errors, never skips.
    try: yield server
    finally: server.stop()

@pytest.fixture()
def conn(pg, monkeypatch, tmp_path):
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path / 'absent-image-policy')
    c = feed_store.connect(pg.sync_dsn)
    drop_public_tables(c)
    schema.ensure_schema(c)
    try: yield c
    finally: c.close()
