from __future__ import annotations

from types import SimpleNamespace

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

    def routed(argv, *, exit_ok, exit_config, exit_not_established):
        calls.append((argv, exit_ok, exit_config, exit_not_established))
        return 29

    monkeypatch.setattr(_main_impl, "main", retained)
    monkeypatch.setattr(cli_main, "run_feed_daily", routed)

    assert cli_main.run(["feed-daily", "--through", "2026-08-28"]) == 29
    assert calls == [(
        ["feed-daily", "--through", "2026-08-28"],
        _main_impl.EXIT_OK,
        _main_impl.EXIT_CONFIG,
        _main_impl.EXIT_NOT_ESTABLISHED,
    )]


def test_cli_run_routes_feed_daily_after_global_verbose(monkeypatch):
    calls = []

    def routed(argv, **kwargs):
        calls.append(argv)
        return 29

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


def _valid_manual_boundary(monkeypatch):
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


def test_feed_daily_calls_ingest_with_validated_session(monkeypatch):
    calls = []

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    conn = Connection()
    _valid_manual_boundary(monkeypatch)
    monkeypatch.setattr(
        feed_cli.runtime_identity,
        "require_feed_producer_identity",
        lambda: {
            "git_commit": "a" * 40,
            "runtime_image_digest": "sha256:" + "b" * 64,
        },
    )
    monkeypatch.setattr(
        feed_cli.SentinelConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(database_url="postgres://test")),
    )
    monkeypatch.setattr(feed_cli.feed_store, "connect", lambda url: conn)
    monkeypatch.setattr(feed_cli.feed_store, "ensure_schema", lambda c: None)
    monkeypatch.setattr(feed_cli.feed_store, "reclaim_orphans", lambda c: 0)

    def daily(c, *, today):
        calls.append((c, today))
        return SimpleNamespace(
            kind="daily", chunks_done=2, rows_written=3, rows_dropped=0
        )

    monkeypatch.setattr(feed_cli.ingest, "daily", daily)

    assert feed_cli.run_feed_daily(
        ["feed-daily", "--through", "2026-08-28"],
        exit_ok=0,
        exit_config=1,
        exit_not_established=2,
    ) == 0
    assert calls == [(conn, "2026-08-28")]
    assert conn.closed is True


def test_feed_daily_checks_config_before_producer_identity(monkeypatch):
    order = []
    _valid_manual_boundary(monkeypatch)

    def config_from_env(cls):
        order.append("config")
        return SimpleNamespace(database_url="postgres://test")

    def missing_producer():
        order.append("producer")
        raise RuntimeError("producer identity missing")

    monkeypatch.setattr(
        feed_cli.SentinelConfig,
        "from_env",
        classmethod(config_from_env),
    )
    monkeypatch.setattr(
        feed_cli.runtime_identity,
        "require_feed_producer_identity",
        missing_producer,
    )

    assert feed_cli.run_feed_daily(
        ["feed-daily", "--through", "2026-08-28"],
        exit_ok=0,
        exit_config=1,
        exit_not_established=2,
    ) == 2
    assert order == ["config", "producer"]
