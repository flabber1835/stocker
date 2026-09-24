"""The actual GO health payload must reconnect under real password authentication."""
import json
from pathlib import Path
import time
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from sentinel.feed import store
from tests.sentinel.test_rolling_go_inputs import (  # noqa: F401
    conn, pg, source, operational_source, ready, issuer_source, published, ROOT,
)


def test_go_health_payload_uses_authenticated_connection_for_writer_exclusion(
        conn, pg, published, monkeypatch, capsys):
    """A real SCRAM challenge exposes credential loss hidden by trust fixtures."""
    role = "health_" + uuid.uuid4().hex
    password = uuid.uuid4().hex  # Ephemeral local test credential, never logged.
    hba = Path(pg.datadir) / "pg_hba.conf"
    original_hba = hba.read_text()
    conn.execute(sql.SQL("CREATE ROLE {} LOGIN SUPERUSER PASSWORD {}").format(
        sql.Identifier(role), sql.Literal(password)))
    conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only=true").format(
        sql.Identifier(role)))
    conn.commit()
    dsn = make_conninfo(conn.info.dsn, user=role, password=password)
    hba.write_text(
        f"host {conn.info.dbname} {role} 127.0.0.1/32 scram-sha-256\n" + original_hba)
    try:
        conn.execute("SELECT pg_reload_conf()")
        conn.commit()
        # Wait for the server's asynchronous reload, proving the fixture really
        # challenges a second connection and cannot pass via trust/PGPASSWORD.
        monkeypatch.delenv("PGPASSWORD", raising=False)
        monkeypatch.setenv("PGPASSFILE", str(Path(pg.datadir) / "absent-passfile"))
        deadline = time.monotonic() + 5
        while True:
            try:
                with store.connect(make_conninfo(dsn, password="")):
                    pass
            except psycopg.OperationalError as exc:
                assert "no password supplied" in str(exc)
                break
            assert time.monotonic() < deadline, "SCRAM authentication was not enforced"
            time.sleep(.05)
        with store.connect(dsn) as authenticated:
            with pytest.raises(psycopg.OperationalError, match="no password supplied"):
                store.connect(authenticated.info.dsn)

        monkeypatch.syspath_prepend(str(ROOT / "scripts"))
        import sentinel_go_validate as go
        assert Path(go.__file__).resolve() == (ROOT / "scripts/sentinel_go_validate.py").resolve()
        monkeypatch.setenv("SENTINEL_DATABASE_URL", dsn)
        with pytest.raises(SystemExit) as completed:
            exec(go._DATABASE_HEALTH_CODE, {})
        assert completed.value.code == 0
        output = capsys.readouterr().out
        report = json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                                 if line.startswith("SENTINEL_GO_DATABASE_HEALTH=")))
        assert all(report["checks"].values()), report
        assert report["checks"]["publication_pin_excludes_writers"]
        assert report["checks"]["repeatable_read_only"]
        assert report["transaction_db_writes"] == 0
        assert report["recent_xnys_sessions"] == 252
        assert password not in output and role not in output
        assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions").fetchone()[0] == 0
    finally:
        conn.rollback()
        hba.write_text(original_hba)
        conn.execute("SELECT pg_reload_conf()")
        conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        conn.commit()
