from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.cli import feed as feed_cli
from sentinel.cli import main as cli_main
from sentinel.cli.authorized_routes import ROUTES as AUTHORIZED_ROUTES
from sentinel.feed import store as feed_store


EXPECTED_OWNERS = {
    "prepare-trading-plan": "sentinel.cli.trading",
    "current-trading-plan": "sentinel.cli.trading",
    "execute-trading-plan": "sentinel.cli.trading",
    "recover-trading-account": "sentinel.cli.trading",
    "bind-empty-live-account": "sentinel.cli.trading",
    "activate-live-automation": "sentinel.cli.trading",
    "release-live-automation-kill-switch": "sentinel.cli.trading",
    "enroll-live-issuer-policy": "sentinel.cli.trading",
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
    "recover-fenced-paper-commands": "sentinel.cli.paper",
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
    "authorize-unsent-paper-recovery": "sentinel.cli.automation",
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
    combined = {**cli_main.ROUTES, **AUTHORIZED_ROUTES}
    assert set(combined) == set(EXPECTED_OWNERS)
    assert len(combined) == 52
    assert not (set(cli_main.ROUTES) & set(AUTHORIZED_ROUTES))
    for command, owner in EXPECTED_OWNERS.items():
        assert combined[command].__module__ == owner, command


def test_parser_and_router_have_exactly_the_same_commands():
    parser = cli_main.build_parser()
    subparsers = next(
        action for action in parser._actions  # noqa: SLF001
        if hasattr(action, "choices") and isinstance(action.choices, dict)
    )
    assert set(subparsers.choices) == (
        set(cli_main.ROUTES) | set(AUTHORIZED_ROUTES))


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


@pytest.mark.parametrize(('status','called','code'), [
    ('ATTESTED_STRUCTURAL', True, 0), ('RECONSTRUCTED_STRUCTURAL', True, 0),
    ('VERIFIED_UNCHANGED', False, 0), ('NOT_STARTED', False, 2),
    ('RECONSTRUCTION_REQUIRED', False, 2)])
def test_manual_daily_uses_the_authenticated_source_boundary(monkeypatch, status, called, code):
    from contextlib import nullcontext
    from sentinel import rolling_checkpoint, rolling_runtime
    calls = []
    conn = object()
    monkeypatch.setattr(feed_cli, '_feed_producer_or_refuse', lambda: {})
    monkeypatch.setattr(feed_store, 'connect', lambda _: nullcontext(conn))
    monkeypatch.setattr(rolling_checkpoint, 'read',
        lambda _: SimpleNamespace(observation_id='paper-shadow', starting_cash='50000'))
    def classify(c, **args):
        assert c is conn and args == dict(observation_id='paper-shadow', starting_cash='50000',
            structural_only=True, unchanged_through='2026-08-28')
        return {'status':status, 'latest_session':'2026-08-27'}
    monkeypatch.setattr(rolling_runtime, 'classify', classify)
    monkeypatch.setattr(rolling_runtime, 'prepare_adjacent', lambda c, **args: calls.append((c,args)))
    args = SimpleNamespace(boundary=SimpleNamespace(through='2026-08-28'))
    assert feed_cli.cmd_feed_daily(SimpleNamespace(database_url='test'), args) == code
    assert bool(calls) is called
    if called:
        assert calls[0][0] is conn
        assert calls[0][1]['through'] == '2026-08-28' and calls[0][1]['previous'] == '2026-08-27'


@pytest.mark.parametrize("date_from,date_to,accepted", [
    (None, None, True), (None, "2026-08-28", True),
    ("2026-07-01", "2026-08-28", False), (None, "2026-08-27", False)])
def test_manual_seed_uses_source_final_first_deployment(monkeypatch, date_from, date_to, accepted):
    from contextlib import nullcontext
    from sentinel.feed import operational_snapshot, rolling_go_inputs

    calls = []
    monkeypatch.setattr(feed_cli, "_feed_producer_or_refuse", lambda: {})
    monkeypatch.setattr(operational_snapshot, "source_final_session", lambda: "2026-08-28")
    monkeypatch.setattr(feed_store, "connect", lambda _: nullcontext("connection"))
    monkeypatch.setattr(rolling_go_inputs, "prepare",
                        lambda c, *, target_session: calls.append((c, target_session)) or {})
    args = SimpleNamespace(date_from=date_from, date_to=date_to)
    result = feed_cli.cmd_feed_seed(SimpleNamespace(database_url="private"), args)
    assert result == (feed_cli.EXIT_OK if accepted else feed_cli.EXIT_CONFIG)
    assert calls == ([("connection", "2026-08-28")] if accepted else [])


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
