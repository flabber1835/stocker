"""Installation failures reproduced at actual HTTP logging and SQL boundaries."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sentinel import schema
from sentinel.cli import _shared, account, authority, automation, paper
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_autonomous_deploy as deploy


@pytest.mark.parametrize("verbose", [False, True])
def test_real_http_logging_preserves_strict_installer_json(verbose):
    # A fresh process uses production basicConfig, without pytest's handlers.
    code = f'''
import json, threading, httpx
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from sentinel.cli._shared import setup_logging
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{{}}")
    def log_message(self, *args): pass
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
setup_logging({verbose!r})
with httpx.Client(trust_env=False) as client:
    client.get(f"http://127.0.0.1:{{server.server_port}}/v2/account").raise_for_status()
server.shutdown(); server.server_close(); thread.join()
print(json.dumps({{"approval_ready": True, "observation_complete": True}}))
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    assert "HTTP Request: GET" in result.stderr
    assert deploy._json_output(result, label="empty account inspection") == {
        "approval_ready": True, "observation_complete": True}
    with pytest.raises(deploy.DeployRefused, match="did not return JSON"):
        deploy._json_output(subprocess.CompletedProcess(
            [], 0, stdout=result.stderr + result.stdout), label="inspection")


HANDLERS = [
    authority.cmd_create_empty_paper_binding_candidate,
    authority._install_administrative_certificate,
    authority._activate_administrative_certificate,
    authority._revoke_administrative_certificate,
    authority._install_system_certificate,
    authority._activate_system_certificate,
    authority._revoke_system_key,
    authority._revoke_system_certificate,
    authority._set_paper_rollout_mode,
    account._migrate_account, account._adopt_restored,
    paper._inspect_empty_paper_account, paper._bind_empty_paper_account,
    automation._activate_paper_automation,
    automation._release_paper_automation_kill,
    automation._acknowledge_paper_alert,
]


def _arguments(tmp_path):
    class Arguments(SimpleNamespace):
        def __getattr__(self, name):
            if name.startswith("confirm_"):
                return True
            raise AttributeError(name)
    certificate = tmp_path / "certificate.json"
    certificate.write_text("{}")
    return Arguments(certificate=str(certificate), mode="PINNED_1_00",
                     deployment_id="qualification", expect_account="test",
                     reason="qualification", notes="qualification")


def _config(dsn):
    return SentinelConfig(alpaca_key="PKTEST", alpaca_secret="test-only",
                          base_url=DEFAULT_BASE_URL,
                          state_dir=Path("/tmp/installation-boundaries"),
                          max_cycles=1, poll_seconds=0, database_url=dsn)


def _call(handler, config, args):
    result = handler(config, args)
    return asyncio.run(result) if inspect.isawaitable(result) else result


@pytest.mark.parametrize("handler", HANDLERS, ids=lambda h: h.__name__)
def test_hot_commands_refuse_missing_schema_before_ddl_or_authority(
        handler, monkeypatch, tmp_path, capsys):
    class Connection:
        closed = False
        def close(self): self.closed = True
    conn = Connection()
    validated = []
    monkeypatch.setattr(store, "connect", lambda _dsn: conn)
    monkeypatch.setattr(_shared, "require_authorized_runtime", lambda *a: None)
    # Imported aliases also need the supported-runtime admission test seam.
    for module in (authority, account, paper, automation):
        monkeypatch.setattr(module, "require_authorized_runtime", lambda *a: None)
    def validate(actual):
        assert actual is conn
        validated.append(True)
        raise schema.SchemaMigrationRefused("missing installed schema")
    def forbidden(_conn):
        raise AssertionError("hot command attempted schema DDL")
    monkeypatch.setattr(schema, "require_runtime_schema", validate)
    monkeypatch.setattr(schema, "ensure_schema", forbidden)
    assert _call(handler, _config("postgresql://test/db"),
                 _arguments(tmp_path)) == _shared.EXIT_NOT_ESTABLISHED
    assert validated == [True]
    assert conn.closed
    assert "missing installed schema" in capsys.readouterr().err


def test_admin_schema_validation_with_actual_health_reader_locks(
        monkeypatch, tmp_path, capsys):
    server = _EphemeralPostgres()
    try:
        server.start()
    except Exception as exc:
        server.stop()
        pytest.skip(f"ephemeral PostgreSQL unavailable: {exc}")
    writer = reader = None
    try:
        writer = store.connect(server.sync_dsn)
        reader = store.connect(server.sync_dsn)
        schema.ensure_schema(writer)  # Explicit isolated fixture migration.
        with reader.cursor() as cur:
            cur.execute("SELECT enabled FROM sentinel_automation_control")
            cur.execute("SELECT count(*) FROM sentinel_observations")
        # Keep the health reader's transaction open. Repeated ALTER on either
        # table would block, as in the retained production deadlock evidence.
        original_validate = schema.require_runtime_schema
        validated = []
        def validate(conn):
            original_validate(conn)
            validated.append(True)
            raise schema.SchemaMigrationRefused("stop after real schema proof")
        monkeypatch.setattr(schema, "require_runtime_schema", validate)
        monkeypatch.setattr(store, "connect", lambda _dsn: writer)
        monkeypatch.setattr(_shared, "require_authorized_runtime", lambda *a: None)
        monkeypatch.setattr(authority, "require_authorized_runtime", lambda *a: None)
        assert _call(authority._install_administrative_certificate,
                     _config(server.sync_dsn), _arguments(tmp_path)) == 2
        assert validated == [True]
        assert "stop after real schema proof" in capsys.readouterr().err
    finally:
        if reader is not None:
            reader.rollback(); reader.close()
        if writer is not None:
            writer.close()
        server.stop()
