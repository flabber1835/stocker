"""Immutable wire terms survive crashes, adoption and observation versions."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
import psycopg

from sentinel import binding, schema
from sentinel.execution import journal, recovery, reconcile
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerExactOrderEvidence, BrokerObservation, BrokerOrder,
    CommandOutcome, Completeness, OrderTerms, Side,
)
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_journal_and_reconcile import cmd, DEPLOY
from tests.sentinel.test_order_terms_schema import pg, _compiled
from tests.support.postgres import drop_public_tables


LIMIT = OrderTerms(order_type="limit", limit_price=Decimal("100.25"))
NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(pg):
    with psycopg.connect(pg.sync_dsn) as connection:
        drop_public_tables(connection)
        schema.ensure_schema(connection)
        binding.bind(connection, deployment_id=DEPLOY.deployment_id,
            broker=DEPLOY.broker, broker_account_id=DEPLOY.broker_account_id)
        connection.execute("UPDATE sentinel_account_binding SET established_at=%s", (NOW-timedelta(days=1),))
        connection.commit()
        yield connection


def order(command, **changes):
    return BrokerOrder(broker_order_id="native-order", client_key=command.client_key,
        instrument=command.instrument, side=command.side, state=S.ACKNOWLEDGED,
        quantity=command.quantity, submitted_at=NOW, order_terms=command.order_terms,
        **changes)


def observation(item):
    identity = BrokerAccountIdentity("sim", "SIM-ACCOUNT")
    exact = BrokerExactOrderEvidence(client_key=item.client_key,
        request_started_at=NOW-timedelta(milliseconds=2), request_completed_at=NOW,
        identity_before=identity, identity_after=identity,
        initial_order_id=item.broker_order_id, order=item)
    return BrokerObservation(observed_at=NOW, started_at=NOW-timedelta(milliseconds=3),
        terminal_recovery_through=NOW, completeness=Completeness.COMPLETE,
        account_identity=identity, orders=(item,), exact_order_evidence=(exact,))


def test_limit_terms_roundtrip_and_cannot_change_under_key(conn):
    original = replace(cmd(), order_terms=LIMIT)
    journal.save_command(conn, original)
    loaded, = journal.load_commands(conn, DEPLOY)
    assert loaded.order_terms == LIMIT and loaded.client_key == original.client_key
    for terms in (OrderTerms(), replace(LIMIT, limit_price=Decimal("100.26"))):
        with pytest.raises(journal.CommandEconomicsChanged, match="order_terms"):
            journal.save_command(conn, replace(original, order_terms=terms))
        conn.rollback()
    assert journal.load_commands(conn, DEPLOY)[0].order_terms == LIMIT


def test_limit_adoption_preserves_exact_terms(conn):
    original = replace(cmd(), order_terms=LIMIT)
    journal.adopt_recovered_order(conn, order(original), deployment=DEPLOY)
    restored, = journal.load_commands(conn, DEPLOY)
    assert restored.order_terms == LIMIT and restored.client_key == original.client_key
    changed = replace(order(original), order_terms=replace(LIMIT, limit_price=Decimal("100.26")))
    with pytest.raises(journal.RecoveredOrderConflict, match="immutable order terms"):
        journal.adopt_recovered_order(conn, changed, deployment=DEPLOY)
    assert journal.load_commands(conn, DEPLOY)[0].order_terms == LIMIT


@pytest.mark.parametrize("terms", [None, OrderTerms(order_type="stop", time_in_force="gtc")])
def test_missing_or_unsupported_owned_terms_cannot_be_adopted(conn, terms):
    native = replace(order(cmd()), order_terms=terms)
    with pytest.raises(journal.RecoveredOrderConflict):
        journal.adopt_recovered_order(conn, native, deployment=DEPLOY)
    assert journal.load_commands(conn, DEPLOY) == ()


def test_recovered_fill_cannot_exceed_its_own_limit(conn):
    native = replace(order(replace(cmd(), order_terms=LIMIT)),
        filled_quantity=Decimal(1), filled_average_price=Decimal("100.26"))
    with pytest.raises(journal.RecoveredOrderConflict, match="fill exceeds"):
        journal.adopt_recovered_order(conn, native, deployment=DEPLOY)
    assert journal.load_commands(conn, DEPLOY) == ()


@pytest.mark.parametrize("terms", [OrderTerms(), replace(LIMIT, limit_price=Decimal("100.26")), None])
def test_open_exact_race_fingerprint_binds_reported_terms(terms):
    initial = order(replace(cmd(), order_terms=LIMIT))
    exact = replace(initial, order_terms=terms)
    assert reconcile._order_observation_fingerprint(initial) != reconcile._order_observation_fingerprint(exact)


@pytest.mark.parametrize("terms", [OrderTerms(), replace(LIMIT, limit_price=Decimal("101")), None])
def test_positive_recovery_and_reconciliation_refuse_changed_terms(terms):
    command = replace(cmd(state=S.UNKNOWN), order_terms=LIMIT)
    found = replace(order(command), order_terms=terms)
    with pytest.raises(BrokerAuthorityRefused, match="order_terms"):
        recovery._assert_order_matches_command(command, found, where="private test")
    assert "order terms" in reconcile._order_command_conflict(found, command)


def test_positive_recovery_refuses_fill_above_limit():
    command = replace(cmd(state=S.UNKNOWN), order_terms=LIMIT)
    found = replace(order(command), filled_quantity=Decimal(1), filled_average_price=Decimal("100.26"))
    with pytest.raises(BrokerAuthorityRefused, match="fill exceeds"):
        recovery._assert_order_matches_command(command, found, where="private test")
    assert "fill exceeds" in reconcile._order_command_conflict(found, command)


def test_dispatch_forwards_protected_terms_without_legacy_signature_fallback():
    calls = []
    class Broker:
        async def submit(self, **kwargs):
            calls.append(kwargs)
            return CommandOutcome(state=S.ACKNOWLEDGED, broker_order_id="native")
    command = replace(cmd(state=S.SEND_PENDING), order_terms=LIMIT)
    sent = asyncio.run(recovery.dispatch(Broker(), command))
    assert sent.order_terms == LIMIT and calls[0]["order_terms"] == LIMIT
    class LegacyOnly:
        async def submit(self, *, client_key, instrument, side, quantity):
            calls.append(dict(client_key=client_key))
            return CommandOutcome(state=S.ACKNOWLEDGED)
    count = len(calls)
    unknown = asyncio.run(recovery.dispatch(LegacyOnly(), command))
    assert unknown.state is S.UNKNOWN and len(calls) == count
    legacy = asyncio.run(recovery.dispatch(LegacyOnly(), cmd(state=S.SEND_PENDING)))
    assert legacy.state is S.ACKNOWLEDGED


def test_new_observation_and_witness_bind_reported_limit(conn):
    native = order(replace(cmd(), order_terms=LIMIT))
    seq = journal.record_observation(conn, observation(native))
    payload = journal.load_observation_payload(conn, seq)
    assert payload["kind"] == journal.OBSERVATION_PAYLOAD_KIND
    assert payload["orders"][0]["order_terms"] == LIMIT.to_dict()
    assert payload["exact_evidence"][0]["order"]["order_terms"] == LIMIT.to_dict()
    key = f"broker-observation:v4:{seq}"
    witness = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (key,)).fetchone()[0]
    assert witness["kind"] == journal.OBSERVATION_WITNESS_KIND
    raw = conn.execute("SELECT orders FROM sentinel_observations WHERE seq=%s", (seq,)).fetchone()[0]
    raw[0]["order_terms"] = replace(LIMIT, limit_price=Decimal("100.26")).to_dict()
    conn.execute("UPDATE sentinel_observations SET orders=%s::jsonb WHERE seq=%s", (json.dumps(raw), seq)); conn.commit()
    with pytest.raises(journal.ObservationEvidenceUncertifiable):
        journal.load_observation_payload(conn, seq)


@pytest.mark.parametrize("compact", [False, True])
def test_historical_observation_bytes_and_digest_remain_valid(conn, compact):
    seq = journal.record_observation(conn, observation(order(cmd())))
    payload = journal.load_observation_payload(conn, seq)
    payload["kind"] = journal.LEGACY_OBSERVATION_PAYLOAD_KIND
    for item in payload["orders"]:
        item.pop("order_terms")
    for exact in payload["exact_evidence"]:
        exact["order"].pop("order_terms")
    digest = journal._canonical_observation_digest(payload)
    rows = conn.execute("SELECT orders FROM sentinel_observations WHERE seq=%s", (seq,)).fetchone()[0]
    for row in rows:
        row.pop("order_terms")
    provenance = conn.execute("SELECT positions FROM sentinel_observation_provenance WHERE observation_seq=%s", (seq,)).fetchone()[0]
    for exact in provenance["exact_evidence"]:
        exact["order"].pop("order_terms")
    evidence = journal._observation_witness(payload, digest) if compact else payload
    conn.execute("UPDATE sentinel_observations SET orders=%s::jsonb WHERE seq=%s", (json.dumps(rows), seq))
    conn.execute("UPDATE sentinel_observation_provenance SET positions=%s::jsonb,canonical_payload_sha256=%s WHERE observation_seq=%s",
        (json.dumps(provenance), digest, seq))
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
        (json.dumps(evidence), f"broker-observation:v4:{seq}")); conn.commit()
    assert journal.load_observation_payload(conn, seq) == payload
    assert journal._canonical_observation_digest(payload) == digest


def test_immutable_terms_falsifier_detects_removed_economics_field(conn, monkeypatch):
    monkeypatch.setattr(journal, "_IMMUTABLE", tuple(
        name for name in journal._IMMUTABLE if name != "order_terms"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_limit_terms_roundtrip_and_cannot_change_under_key(conn)


def test_recovery_terms_falsifier_detects_removed_positive_identity_guard(monkeypatch):
    monkeypatch.setattr(recovery, "_assert_order_matches_command", _compiled(
        recovery._assert_order_matches_command,
        "if found.order_terms != command.order_terms:", "if False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_positive_recovery_and_reconciliation_refuse_changed_terms(OrderTerms())


def test_fill_cap_falsifier_detects_removed_positive_fill_guard(monkeypatch):
    monkeypatch.setattr(recovery, "_assert_order_matches_command", _compiled(
        recovery._assert_order_matches_command,
        "if (command.order_terms.limit_price is not None", "if (False"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_positive_recovery_refuses_fill_above_limit()


def test_adopted_fill_cap_falsifier_detects_removed_cap_guard(conn, monkeypatch):
    monkeypatch.setattr(journal, "_owned_order_terms", _compiled(
        journal._owned_order_terms,
        "if (order.order_terms.limit_price is not None", "if (False"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_recovered_fill_cannot_exceed_its_own_limit(conn)


def test_race_fingerprint_falsifier_detects_omitted_terms(monkeypatch):
    monkeypatch.setattr(reconcile, "_order_observation_fingerprint", _compiled(
        reconcile._order_observation_fingerprint,
        "order.side, order.quantity, order.order_terms,", "order.side, order.quantity,"))
    with pytest.raises(AssertionError):
        test_open_exact_race_fingerprint_binds_reported_terms(OrderTerms())
