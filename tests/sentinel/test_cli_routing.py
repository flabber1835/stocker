from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.cli import feed as feed_cli
from sentinel.cli import main as cli_main
from sentinel.feed import store as feed_store


EXPECTED_OWNERS = {
    "status": "sentinel.cli.status",
    "shadow-status": "sentinel.cli.status",
    "shadow-run": "sentinel.cli.status",
    "feed-status": "sentinel.cli.feed",
    "feed-seed": "sentinel.cli.feed",
    "feed-daily": "sentinel.cli.feed",
    "check-data": "sentinel.cli.feed",
    "rejection-audit": "sentinel.cli.feed",
    "feed-repair": "sentinel.cli.feed",
    "identity": "sentinel.cli.feed",
    "migration-plan": "sentinel.cli.account",
    "target-book": "sentinel.cli.account",
    "plan": "sentinel.cli.account",
    "migrate-account": "sentinel.cli.account",
    "adopt-restored-account": "sentinel.cli.account",
    "establish-ownership": "sentinel.cli.account",
    "compare-paper-warmup": "sentinel.cli.paper",
    "inspect-paper-account": "sentinel.cli.paper",
    "inspect-empty-paper-account": "sentinel.cli.paper",
    "bind-empty-paper-account": "sentinel.cli.paper",
    "prepare-paper-plan": "sentinel.cli.paper",
    "current-paper-plan": "sentinel.cli.paper",
    "execute-paper-plan": "sentinel.cli.paper",
    "create-paper-observation-candidate": "sentinel.cli.authority",
    "create-empty-paper-binding-candidate": "sentinel.cli.authority",
    "install-administrative-certificate": "sentinel.cli.authority",
    "activate-administrative-certificate": "sentinel.cli.authority",
    "revoke-administrative-certificate": "sentinel.cli.authority",
    "install-system-certificate": "sentinel.cli.authority",
    "activate-system-certificate": "sentinel.cli.authority",
    "rotate-system-certificate": "sentinel.cli.authority",
    "revoke-system-certificate": "sentinel.cli.authority",
    "revoke-system-key": "sentinel.cli.authority",
    "set-paper-rollout-mode": "sentinel.cli.authority",
    "automation-status": "sentinel.cli.automation",
    "automation-health": "sentinel.cli.automation",
    "activate-paper-automation": "sentinel.cli.automation",
    "release-paper-automation-kill-switch": "sentinel.cli.automation",
    "engage-paper-automation-kill-switch": "sentinel.cli.automation",
    "deactivate-paper-automation": "sentinel.cli.automation",
    "acknowledge-paper-alert": "sentinel.cli.automation",
    "automation-run": "sentinel.cli.automation",
}


def test_executable_boundary_is_direct_and_has_no_compatibility_proxy():
    import sentinel.__main__ as executable

    source = inspect.getsource(executable)
    assert "from sentinel.cli.main import main" in source
    assert "_main_impl" not in source
    assert "__getattr__" not in source
    assert "setattr(" not in source


def test_cli_has_one_parser_construction_and_one_parse_call():
    cli_dir = Path(cli_main.__file__).parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(cli_dir.glob("*.py"))
    )
    assert source.count("argparse.ArgumentParser(") == 1
    assert source.count(".parse_args(") == 1


def test_every_command_has_one_static_direct_owner():
    assert set(cli_main.ROUTES) == set(EXPECTED_OWNERS)
    assert len(cli_main.ROUTES) == 42
    for command, owner in EXPECTED_OWNERS.items():
        assert cli_main.ROUTES[command].__module__ == owner, command


def test_parser_and_router_have_exactly_the_same_commands():
    parser = cli_main.build_parser()
    subparsers = next(
        action for action in parser._actions  # noqa: SLF001
        if hasattr(action, "choices") and isinstance(action.choices, dict)
    )
    assert set(subparsers.choices) == set(cli_main.ROUTES)


def test_cli_router_invokes_selected_owner_once(monkeypatch):
    calls = []

    def routed(config, args):
        calls.append((config, args.command))
        return 17

    monkeypatch.setitem(cli_main.ROUTES, "status", routed)
    monkeypatch.setattr(
        cli_main.SentinelConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace()),
    )
    assert cli_main.main(["status"]) == 17
    assert len(calls) == 1
    assert calls[0][1] == "status"


def test_feed_daily_calls_ingest_with_validated_session(monkeypatch):
    calls = []

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    conn = Connection()
    args = SimpleNamespace(
        through=["2026-08-28"],
        boundary=SimpleNamespace(through="2026-08-28"),
    )
    monkeypatch.setattr(
        "sentinel.identity.require_feed_producer_identity",
        lambda: {
            "git_commit": "a" * 40,
            "runtime_image_digest": "sha256:" + "b" * 64,
        },
    )
    monkeypatch.setattr(feed_store, "connect", lambda url: conn)
    monkeypatch.setattr(feed_store, "require_feed_schema", lambda c: None)
    monkeypatch.setattr(feed_store, "reclaim_orphans", lambda c: 0)

    def daily(c, *, today):
        calls.append((c, today))
        return SimpleNamespace(
            kind="daily", chunks_done=2, rows_written=3, rows_dropped=0)

    monkeypatch.setattr("sentinel.feed.ingest.daily", daily)
    config = SimpleNamespace(database_url="postgres://test")
    assert feed_cli.cmd_feed_daily(config, args) == 0
    assert calls == [(conn, "2026-08-28")]
    assert conn.closed is True


def test_feed_daily_boundary_refuses_before_configuration(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_main.SentinelConfig,
        "from_env",
        classmethod(lambda cls: (_ for _ in ()).throw(
            AssertionError("configuration read before boundary refusal"))),
    )
    assert cli_main.main(["feed-daily"]) == cli_main.EXIT_CONFIG
    assert "requires" in capsys.readouterr().err


def test_feed_daily_rejects_duplicate_through_before_configuration(
        monkeypatch, capsys):
    monkeypatch.setattr(
        cli_main.SentinelConfig,
        "from_env",
        classmethod(lambda cls: (_ for _ in ()).throw(
            AssertionError("configuration read before boundary refusal"))),
    )
    assert cli_main.main([
        "feed-daily", "--through", "2026-08-28",
        "--through", "2026-08-28",
    ]) == cli_main.EXIT_CONFIG
    assert "exactly one" in capsys.readouterr().err


def test_feed_daily_help_contract_is_stable(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main.main(["feed-daily", "--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == (
        "usage: sentinel feed-daily [-h] --through YYYY-MM-DD\n\n"
        "Fetch and publish through one explicit fully closed XNYS session.\n\n"
        "options:\n"
        "  -h, --help            show this help message and exit\n"
        "  --through YYYY-MM-DD  required closed XNYS session boundary\n"
    )
