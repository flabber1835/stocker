"""The entrypoint's refusals, and that `plan` is genuinely read-only.

Two failures matter here and neither is about argument parsing:

  * Sentinel starting against the REAL trading API;
  * `plan` — the command whose entire promise is "submits nothing" — submitting
    something, or advancing the ownership log.

The credential refusal is subtler than it looks and is tested for the reason in
its message: with no credentials every broker read returns empty, an empty
account reads as ALREADY FLAT, and Sentinel would record ownership over a book
it never saw.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from fakes import FakeBroker  # noqa: E402
from sentinel import __main__ as cli  # noqa: E402
from sentinel.config import (  # noqa: E402
    DEFAULT_BASE_URL,
    LiveEndpointRefused,
    MissingCredentials,
    SentinelConfig,
)
from sentinel.ownership import OwnershipState  # noqa: E402
from sentinel.store import FileOwnershipStore, ownership_established, record  # noqa: E402

S = OwnershipState


def env(**over):
    base = {
        "ALPACA_API_KEY": "PKTESTKEY1234",
        "ALPACA_SECRET_KEY": "secret",
        "ALPACA_BASE_URL": DEFAULT_BASE_URL,
        "SENTINEL_STATE_DIR": "/tmp/sentinel-test",
    }
    base.update(over)
    return base


class TestPaperOnly:
    def test_the_LIVE_endpoint_is_refused(self):
        with pytest.raises(LiveEndpointRefused, match="api.alpaca.markets"):
            SentinelConfig.from_env(env(ALPACA_BASE_URL="https://api.alpaca.markets"))

    @pytest.mark.parametrize("extra", [
        {"LIVE_TRADING_ENABLED": "true"},
        {"PAPER_ONLY": "false"},
        {"SENTINEL_ALLOW_LIVE": "1"},
        {"SENTINEL_ALLOW_LIVE_ENDPOINT": "yes"},
        {"LIVE_TRADING_ENABLED": "true", "PAPER_ONLY": "false"},
    ])
    def test_there_is_no_override(self, extra, monkeypatch):
        """A flag that could grant a live mandate is the same slip the hardcoded
        trade_type was. No env var combination may unlock the live endpoint.

        The overrides are set in the PROCESS environment as well as passed in the
        mapping. An earlier version only did the latter, and a deliberately
        introduced `os.getenv('SENTINEL_ALLOW_LIVE')` escape hatch sailed through
        it — the test was checking a channel nobody would use to add one.
        """
        for k, v in extra.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(LiveEndpointRefused):
            SentinelConfig.from_env(
                env(ALPACA_BASE_URL="https://api.alpaca.markets", **extra))

    def test_no_override_reaches_the_guard_from_the_process_env_either(self, monkeypatch):
        """`from_env` with NO mapping at all — the real production path."""
        for k, v in env(ALPACA_BASE_URL="https://api.alpaca.markets",
                        SENTINEL_ALLOW_LIVE="1").items():
            monkeypatch.setenv(k, v)
        with pytest.raises(LiveEndpointRefused):
            SentinelConfig.from_env()

    def test_paper_and_unknown_hosts_are_accepted(self):
        for url in (DEFAULT_BASE_URL, "http://alpaca-sim:9000", "http://localhost:9"):
            assert SentinelConfig.from_env(env(ALPACA_BASE_URL=url)).is_live_endpoint is False

    def test_the_cli_exits_1_rather_than_traceback(self, monkeypatch):
        for k, v in env(ALPACA_BASE_URL="https://api.alpaca.markets").items():
            monkeypatch.setenv(k, v)
        assert cli.main(["status"]) == cli.EXIT_CONFIG


class TestCredentialRefusal:
    @pytest.mark.parametrize("over", [
        {"ALPACA_API_KEY": ""},
        {"ALPACA_SECRET_KEY": ""},
        {"ALPACA_API_KEY": "demo"},
    ])
    def test_missing_or_placeholder_credentials_refuse(self, over):
        cfg = SentinelConfig.from_env(env(**over))
        with pytest.raises(MissingCredentials, match="ALREADY FLAT"):
            cfg.assert_credentials()

    def test_status_still_works_WITHOUT_credentials(self, monkeypatch, tmp_path, capsys):
        """The moment you most want to inspect state is when the environment is
        wrong. A status command that needs credentials is useless then."""
        for k, v in env(ALPACA_API_KEY="", SENTINEL_STATE_DIR=str(tmp_path)).items():
            monkeypatch.setenv(k, v)
        assert cli.main(["status"]) == cli.EXIT_OK
        out = json.loads(capsys.readouterr().out)
        # The BINDING answers this now, not the file. With no database
        # configured the honest answer is UNKNOWN — never NOT_OWNED, which
        # would invite someone to rerun a migration.
        assert out["ownership"] == "UNKNOWN"
        assert out["authority"] == "none"
        assert out["wealth_core_bootstrap_allowed"] is False


class TestPlanIsReadOnly:
    """`plan`'s whole promise is that it changes nothing."""

    def _wire(self, monkeypatch, tmp_path, broker):
        for k, v in env(SENTINEL_STATE_DIR=str(tmp_path)).items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(cli, "build_broker", lambda cfg: broker)

    def test_plan_submits_NOTHING_and_writes_NOTHING(self, monkeypatch, tmp_path, capsys):
        broker = FakeBroker({"AAPL": 10, "MSFT": 5})
        self._wire(monkeypatch, tmp_path, broker)

        assert cli.main(["plan"]) == cli.EXIT_OK
        out = json.loads(capsys.readouterr().out)

        assert broker.closes == [], "plan submitted a close"
        assert broker.cancelled == [], "plan cancelled an order"
        assert FileOwnershipStore(tmp_path / "ownership.jsonl").events() == [], \
            "plan advanced the ownership log"
        assert sorted(out["plan"]["would_liquidate"]) == ["AAPL", "MSFT"]
        assert out["dry_run"] is True

    def test_plan_on_an_OWNED_book_reports_no_liquidation(self, monkeypatch, tmp_path, capsys):
        broker = FakeBroker({"AAPL": 100})
        self._wire(monkeypatch, tmp_path, broker)
        record(FileOwnershipStore(tmp_path / "ownership.jsonl"),
               S.SENTINEL_OWNERSHIP_ESTABLISHED)

        assert cli.main(["plan"]) == cli.EXIT_OK
        out = json.loads(capsys.readouterr().out)
        assert out["plan"]["would_liquidate"] == []
        assert out["ownership_established"] is True


class TestEstablishOwnershipIsRetired:
    """The subcommand survives ONLY to refuse and to name its replacement.

    It used to classify an account as a legacy Stocker book whenever a JSONL
    file said nothing, so losing one file on one volume re-armed a liquidation
    against a Wealth Core book. Deleting the subcommand outright would leave a
    stale runbook — or a `restart: unless-stopped` service definition someone
    adds later — with a bare argparse error and no idea what to run instead, on
    the one command whose history is that it could liquidate an account it
    should not have.

    The handover's own exit codes are covered in test_binding_and_handover.py,
    against a real database, because the binding is database state now.
    """

    def test_it_refuses(self, monkeypatch, tmp_path):
        for k, v in env(SENTINEL_STATE_DIR=str(tmp_path)).items():
            monkeypatch.setenv(k, v)
        assert cli.main(["establish-ownership"]) == cli.EXIT_CONFIG

    def test_it_liquidates_NOTHING(self, monkeypatch, tmp_path):
        broker = FakeBroker({"AAPL": 10})
        for k, v in env(SENTINEL_STATE_DIR=str(tmp_path)).items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(cli, "build_broker", lambda cfg: broker)

        cli.main(["establish-ownership", "--poll-seconds", "0"])
        assert broker.closes == []
        assert ownership_established(
            FileOwnershipStore(tmp_path / "ownership.jsonl")) is False

    def test_it_names_the_replacement(self, monkeypatch, tmp_path, capsys):
        for k, v in env(SENTINEL_STATE_DIR=str(tmp_path)).items():
            monkeypatch.setenv(k, v)
        cli.main(["establish-ownership"])
        assert "migrate-account" in capsys.readouterr().err

    def test_migrate_account_refuses_without_a_database(self, monkeypatch, tmp_path):
        """The binding is database state; there is no file fallback, because a
        file fallback is what made absence dangerous."""
        for k, v in env(SENTINEL_STATE_DIR=str(tmp_path)).items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
        assert cli.main(["migrate-account", "--deployment-id", "nas-1"]) \
            == cli.EXIT_CONFIG

    def test_adoption_requires_the_human_assertion(self, monkeypatch, tmp_path,
                                                   capsys):
        """Nothing observable from this host distinguishes 'the old appliance is
        stopped' from 'unreachable from here', so the fence is procedural."""
        for k, v in env(SENTINEL_STATE_DIR=str(tmp_path),
                        SENTINEL_DATABASE_URL="postgresql://x/y").items():
            monkeypatch.setenv(k, v)
        assert cli.main(["adopt-restored-account"]) == cli.EXIT_CONFIG
        assert "revoked" in capsys.readouterr().err


class TestRedaction:
    def test_the_secret_is_never_printed(self, monkeypatch, tmp_path, capsys):
        for k, v in env(ALPACA_API_KEY="PKSUPERSECRETKEY", ALPACA_SECRET_KEY="TOPSECRET",
                        SENTINEL_STATE_DIR=str(tmp_path)).items():
            monkeypatch.setenv(k, v)
        cli.main(["status"])
        out = capsys.readouterr().out
        assert "TOPSECRET" not in out
        assert "PKSUPERSECRETKEY" not in out
        assert "...TKEY" in out, "the key tail should still distinguish two accounts"
