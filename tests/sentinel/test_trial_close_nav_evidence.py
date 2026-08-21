"""Immutable broker close-NAV evidence is exact and session bound."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import trial_close
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerCloseValuation,
)
from sentinel.execution.identity import DeploymentIdentity


SESSION = date(2026, 8, 20)
CLOSE = datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc)


class JsonStateConnection:
    """The two-statement processed-session store used by this boundary."""

    def __init__(self):
        self.rows = {}
        self.result = None
        self.rowcount = 0
        self.commits = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split()).lower()
        if normalized.startswith(
                "select session,state from sentinel_processed_sessions"):
            self.result = self.rows.get(params[0])
            self.rowcount = 1 if self.result is not None else 0
            return
        if normalized.startswith("insert into sentinel_processed_sessions"):
            name, raw_session, raw_state = params
            if name in self.rows:
                self.rowcount = 0
                return
            self.rows[name] = (
                date.fromisoformat(str(raw_session)), json.loads(raw_state))
            self.rowcount = 1
            return
        raise AssertionError(f"unexpected close-NAV SQL: {statement}")

    def fetchone(self):
        return self.result

    def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def exact_close(monkeypatch):
    def resolve(session):
        if session != SESSION:
            raise ValueError("not a modeled XNYS session")
        return CLOSE

    monkeypatch.setattr(trial_close, "_official_close", resolve)


@pytest.fixture
def deployment():
    return DeploymentIdentity(
        deployment_id="trial-appliance", broker="alpaca",
        broker_account_id="PA-1", takeover_epoch=7)


@pytest.fixture
def valuation():
    raw = {
        "timestamp": 1787256000,
        "equity": 125000.25,
        "timeframe": "1D",
    }
    return BrokerCloseValuation(
        identity=BrokerAccountIdentity(
            broker="alpaca", account_id="PA-1"),
        requested_session=SESSION,
        equity=Decimal("125000.2500"),
        source_timestamp=1787256000,
        source_timestamp_unit="unix_seconds",
        source_timeframe="1D",
        source="alpaca_portfolio_history",
        semantics="ACCEPTED_1D_CLOSE_POINT",
        valuation_at=CLOSE,
        request_started_at=CLOSE + timedelta(minutes=2),
        request_completed_at=CLOSE + timedelta(minutes=2, seconds=1),
        query=(("period", "1D"), ("timeframe", "1D")),
        raw=raw,
    )


def _sha(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def test_typed_close_point_is_recorded_in_the_versioned_namespace(
        deployment, valuation):
    conn = JsonStateConnection()

    evidence = trial_close.record_close_nav_evidence(
        conn, deployment=deployment, valuation=valuation)

    cursor = "trial-close-nav:v1:2026-08-20"
    assert trial_close.close_nav_cursor(SESSION) == cursor
    assert set(conn.rows) == {cursor}
    assert conn.rows[cursor][0] == SESSION
    assert evidence["kind"] == "sentinel-trial-close-nav/v1"
    assert evidence["requested_session"] == SESSION.isoformat()
    assert evidence["deployment"] == {
        "deployment_id": "trial-appliance",
        "broker": "alpaca",
        "broker_account_id": "PA-1",
        "takeover_epoch": 7,
    }
    assert evidence["source"] == "alpaca_portfolio_history"
    assert evidence["semantics"] == "ACCEPTED_1D_CLOSE_POINT"
    assert evidence["query"] == [
        ["period", "1D"], ["timeframe", "1D"]]
    assert evidence["source_timestamp"] == 1787256000
    assert evidence["source_timestamp_unit"] == "unix_seconds"
    assert evidence["official_xnys_close_at"] == CLOSE.isoformat()
    assert evidence["equity"] == "125000.25"
    assert evidence["raw_payload_sha256"] == _sha(valuation.raw)
    unhashed = {
        key: value for key, value in evidence.items()
        if key != "evidence_sha256"}
    assert evidence["evidence_sha256"] == _sha(unhashed)
    assert trial_close.load_close_nav_evidence(
        conn, session=SESSION, deployment=deployment) == evidence
    assert conn.commits == 1


def test_plain_duck_typed_close_point_is_accepted(deployment, valuation):
    conn = JsonStateConnection()
    duck_point = SimpleNamespace(**vars(valuation))

    evidence = trial_close.record_close_nav_evidence(
        conn, deployment=deployment, valuation=duck_point)

    assert evidence["equity"] == "125000.25"
    assert evidence["deployment"]["takeover_epoch"] == 7


def test_retry_of_identical_source_point_keeps_first_request_bracket(
        deployment, valuation):
    conn = JsonStateConnection()
    first = trial_close.record_close_nav_evidence(
        conn, deployment=deployment, valuation=valuation)
    later_read = replace(
        valuation,
        equity=Decimal("125000.25"),
        request_started_at=CLOSE + timedelta(hours=1),
        request_completed_at=CLOSE + timedelta(hours=1, seconds=2))

    second = trial_close.record_close_nav_evidence(
        conn, deployment=deployment, valuation=later_read)

    assert second == first
    assert second["request_started_at"] == (
        CLOSE + timedelta(minutes=2)).isoformat()
    assert len(conn.rows) == 1
    assert conn.commits == 1


@pytest.mark.parametrize("change", [
    {"source_timestamp": 1787256001},
    {"source_timestamp_unit": "unix_milliseconds"},
    {"equity": Decimal("125000.26")},
    {"source": "different_history_endpoint"},
    {"semantics": "DIFFERENT_POINT_SEMANTICS"},
    {"query": (("period", "2D"), ("timeframe", "1D"))},
    {"raw": {"timestamp": 1787256000, "equity": 125000.26}},
])
def test_changed_historical_source_point_is_a_revision(
        deployment, valuation, change):
    conn = JsonStateConnection()
    trial_close.record_close_nav_evidence(
        conn, deployment=deployment, valuation=valuation)

    with pytest.raises(
            trial_close.TrialCloseNavHistoricalRevision,
            match="historical close-NAV revision"):
        trial_close.record_close_nav_evidence(
            conn, deployment=deployment, valuation=replace(valuation, **change))


@pytest.mark.parametrize("change, message", [
    ({"source_timestamp_unit": None}, "label unit"),
    ({"valuation_at": None}, "valuation_at"),
    ({"valuation_at": CLOSE + timedelta(seconds=1)}, "official XNYS close"),
    ({"request_started_at": CLOSE - timedelta(seconds=1)},
     "requested before"),
])
def test_incomplete_or_non_close_authority_is_refused(
        deployment, valuation, change, message):
    with pytest.raises(trial_close.TrialCloseNavRefused, match=message):
        trial_close.build_close_nav_evidence(
            deployment=deployment, valuation=replace(valuation, **change))


def test_non_decimal_equity_and_wrong_account_are_refused(
        deployment, valuation):
    string_equity = SimpleNamespace(**{
        **vars(valuation), "equity": "125000.25"})
    with pytest.raises(trial_close.TrialCloseNavRefused, match="Decimal"):
        trial_close.build_close_nav_evidence(
            deployment=deployment, valuation=string_equity)

    wrong_account = replace(
        valuation,
        identity=BrokerAccountIdentity(
            broker="alpaca", account_id="PA-OTHER"))
    with pytest.raises(trial_close.TrialCloseNavRefused, match="binding"):
        trial_close.build_close_nav_evidence(
            deployment=deployment, valuation=wrong_account)


def test_load_rejects_db_date_kind_hash_and_binding_corruption(
        deployment, valuation):
    def recorded():
        connection = JsonStateConnection()
        trial_close.record_close_nav_evidence(
            connection, deployment=deployment, valuation=valuation)
        return connection

    cursor = trial_close.close_nav_cursor(SESSION)

    wrong_date = recorded()
    wrong_date.rows[cursor] = (
        SESSION - timedelta(days=1), wrong_date.rows[cursor][1])
    with pytest.raises(trial_close.TrialCloseNavRefused, match="date/session"):
        trial_close.load_close_nav_evidence(
            wrong_date, session=SESSION, deployment=deployment)

    wrong_kind = recorded()
    wrong_kind.rows[cursor][1]["kind"] = "sentinel-trial-close-nav/v2"
    with pytest.raises(trial_close.TrialCloseNavRefused, match="kind"):
        trial_close.load_close_nav_evidence(
            wrong_kind, session=SESSION, deployment=deployment)

    wrong_hash = recorded()
    wrong_hash.rows[cursor][1]["equity"] = "999999"
    with pytest.raises(trial_close.TrialCloseNavRefused, match="hash is corrupt"):
        trial_close.load_close_nav_evidence(
            wrong_hash, session=SESSION, deployment=deployment)

    another_epoch = DeploymentIdentity(
        deployment_id=deployment.deployment_id, broker=deployment.broker,
        broker_account_id=deployment.broker_account_id, takeover_epoch=8)
    with pytest.raises(
            trial_close.TrialCloseNavRefused, match="takeover epoch"):
        trial_close.load_close_nav_evidence(
            recorded(), session=SESSION, deployment=another_epoch)
