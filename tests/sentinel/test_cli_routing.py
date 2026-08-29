from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel import _main_impl
from sentinel.cli import feed as feed_cli
from sentinel.cli import main as cli_main


def test_cli_run_resolves_retained_main_dynamically(monkeypatch):
    calls = []

    def retained(argv):
        calls.append(argv)
        return 17

    monkeypatch.setattr(_main_impl, "main", retained)

    assert cli_main.run(["status"]) == 17
    assert calls == [["status"]]


def test_cli_run_routes_feed_daily_to_feed_owner(monkeypatch):
    calls = []

    def retained(argv):
        return 23

    def routed(argv, *, retained_main, exit_ok, exit_config):
        calls.append((argv, retained_main, exit_ok, exit_config))
        return 29

    monkeypatch.setattr(_main_impl, "main", retained)
    monkeypatch.setattr(cli_main, "run_feed_daily", routed)

    assert cli_main.run(["feed-daily", "--through", "2026-08-28"]) == 29
    assert calls == [(
        ["feed-daily", "--through", "2026-08-28"],
        retained,
        _main_impl.EXIT_OK,
        _main_impl.EXIT_CONFIG,
    )]


def test_cli_run_routes_feed_daily_after_global_verbose(monkeypatch):
    calls = []

    def retained(argv):
        return 23

    def routed(argv, *, retained_main, exit_ok, exit_config):
        calls.append(argv)
        return 29

    monkeypatch.setattr(_main_impl, "main", retained)
    monkeypatch.setattr(cli_main, "run_feed_daily", routed)

    assert cli_main.run(["--verbose", "feed-daily"]) == 29
    assert calls == [["--verbose", "feed-daily"]]


def test_cli_run_does_not_route_argument_value_named_feed_daily(monkeypatch):
    retained_calls = []
    routed_calls = []

    def retained(argv):
        retained_calls.append(argv)
        return 37

    def routed(*args, **kwargs):
        routed_calls.append((args, kwargs))
        return 41

    monkeypatch.setattr(_main_impl, "main", retained)
    monkeypatch.setattr(cli_main, "run_feed_daily", routed)

    argv = ["migration-plan", "--deployment-id", "feed-daily"]
    assert cli_main.run(argv) == 37
    assert retained_calls == [argv]
    assert routed_calls == []


def test_feed_daily_scopes_explicit_session_to_retained_dispatch(monkeypatch):
    calls = []

    def original_daily(conn, *args, **kwargs):
        calls.append((conn, args, kwargs))
        return "progress"

    monkeypatch.setattr(feed_cli.ingest, "daily", original_daily)
    monkeypatch.setattr(
        feed_cli.manual_daily,
        "extract_through",
        lambda argv: (["feed-daily"], "2026-08-28"),
    )
    monkeypatch.setattr(
        feed_cli.manual_daily,
        "validate_through",
        lambda raw: SimpleNamespace(
            through=raw,
            calendar_version="XNYS-test",
            latest_closed="2026-08-28",
        ),
    )

    def retained(argv):
        assert argv == ["feed-daily"]
        assert feed_cli.ingest.daily(None) == "progress"
        return 31

    assert feed_cli.run_feed_daily(
        ["feed-daily", "--through", "2026-08-28"],
        retained_main=retained,
        exit_ok=0,
        exit_config=1,
    ) == 31
    assert calls == [(None, (), {"today": "2026-08-28"})]
    assert feed_cli.ingest.daily is original_daily


def test_feed_daily_restores_ingest_after_dispatch_failure(monkeypatch):
    def original_daily(conn, *args, **kwargs):
        return None

    monkeypatch.setattr(feed_cli.ingest, "daily", original_daily)
    monkeypatch.setattr(
        feed_cli.manual_daily,
        "extract_through",
        lambda argv: (["feed-daily"], "2026-08-28"),
    )
    monkeypatch.setattr(
        feed_cli.manual_daily,
        "validate_through",
        lambda raw: SimpleNamespace(
            through=raw,
            calendar_version="XNYS-test",
            latest_closed="2026-08-28",
        ),
    )

    def retained(argv):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        feed_cli.run_feed_daily(
            ["feed-daily", "--through", "2026-08-28"],
            retained_main=retained,
            exit_ok=0,
            exit_config=1,
        )

    assert feed_cli.ingest.daily is original_daily
