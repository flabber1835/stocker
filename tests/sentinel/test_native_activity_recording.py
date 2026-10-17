from __future__ import annotations

import asyncio
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from sentinel.execution.alpaca_history import HistoryLimits, read_account_history
from sentinel.execution.native_activity import decode_canonical_json
from sentinel.execution.native_readonly import ReadOnlyAlpacaClient
from tests.support.native_activity_recording import (
    ActivityRecording, FIXTURE_KEY, FIXTURE_SECRET, RecordingReplay, RecordedExchange,
    SCENARIO_IDS, load_recording, recording_bytes, scenario_recording,
)
from tools.sentinel_native_acceptance import MANDATORY_SCENARIOS


async def replay(recording, *, limits=None, prior=()):
    transport = RecordingReplay(recording.exchanges, base_url=recording.subject.base_url)
    async with transport.client() as http:
        async with ReadOnlyAlpacaClient(recording.subject, api_key=FIXTURE_KEY,
                                       secret_key=FIXTURE_SECRET, http_client=http) as client:
            batch = await read_account_history(client, after=recording.after, through=recording.through,
                                               limits=limits, prior_evidence=prior)
    transport.assert_consumed()
    assert all(method == "GET" for method, _path in transport.requests)
    return batch


@pytest.mark.parametrize("scenario", SCENARIO_IDS)
def test_mandatory_native_history_scenario(scenario):
    assert SCENARIO_IDS == MANDATORY_SCENARIOS
    recording, limits, prior = scenario_recording(scenario)
    batch = asyncio.run(replay(recording, limits=limits, prior=prior))
    if scenario in {"valid-native-fill", "late-business-time", "exact-order-enrichment"}:
        assert batch.projection_ready and len(batch.fills) == 1
        assert batch.fills[0].quantity.as_tuple().exponent == 0
        assert str(batch.fills[0].quantity * batch.fills[0].price) == "20.50"
        if scenario == "late-business-time":
            assert batch.fills[0].executed_at.year == 2020
    elif scenario == "dividend-fee-transfer":
        assert batch.projection_ready and len(batch.cash_activities) == 3
        assert [item.classification for item in batch.cash_activities] == ["INTERNAL", "INTERNAL", "EXTERNAL"]
        assert not batch.fills
    elif scenario == "tied-created-at":
        assert batch.projection_ready and len(batch.cash_activities) == 2
        activity_reads = [item for item in batch.reads if item.path == "/v2/account/activities"]
        assert len(activity_reads) == 2
        assert decode_canonical_json(activity_reads[-1].params_json)["page_token"] == "tie-2"
    elif scenario == "duplicate-replay":
        assert batch.projection_ready and set(batch.replayed_native_ids) == {"activity-1"}
        assert len(batch.evidence) == 1
        assert not batch.fills and not batch.cash_activities
    elif scenario == "empty-history":
        assert batch.traversal_exhausted and batch.termination == "EMPTY_PAGE"
        assert not batch.fills and not batch.cash_activities
    else:
        assert not batch.projection_ready
        assert not batch.fills and not batch.cash_activities
        reasons = {item.reason_code for item in batch.quarantines}
        expected = {
            "same-id-changed": "CHANGED_NATIVE_ACTIVITY_ID",
            "unknown-event": "UNSUPPORTED_NATIVE_ACTIVITY",
            "correction-quarantine": "CORRECTION_REQUIRES_REBOOKING",
            "security-transfer-quarantine": "UNSUPPORTED_SECURITIES_ACTIVITY",
            "malformed-decimal": "INVALID_NATIVE_DECIMAL",
            "mismatched-exact-order": "EXACT_ORDER_REQUIRED",
        }
        if scenario in expected:
            assert expected[scenario] in reasons
        elif scenario == "truncated-pagination":
            assert batch.termination == "PAGE_LIMIT" and not batch.traversal_exhausted
        elif scenario == "cursor-cycle":
            assert batch.termination == "REPEATED_ACTIVITY_CURSOR" and not batch.traversal_exhausted
        elif scenario == "wrong-account":
            assert batch.termination == "FINAL_ACCOUNT_VERIFICATION_REFUSED" and not batch.traversal_exhausted


def test_offline_history_never_promotes_native_guarantees():
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    from sentinel.execution.broker_cash import PlanCashBaseline
    for scenario in SCENARIO_IDS:
        recording, limits, prior = scenario_recording(scenario)
        batch = asyncio.run(replay(recording, limits=limits, prior=prior))
        assert not batch.provider_finality_proven
        assert not batch.settlement_proven
        assert not batch.restore_grade_recovery_proven
        assert not batch.live_authority_granted
    assert not AlpacaExecutionBroker.capabilities.complete_order_pagination
    assert not AlpacaExecutionBroker.capabilities.recent_fill_history
    assert not AlpacaExecutionBroker.restore_grade_order_recovery
    assert not AlpacaExecutionBroker.account_snapshot_freshness
    assert not AlpacaExecutionBroker.financial_activity_sse
    assert PlanCashBaseline.close_cash_finality_authoritative.fget(None) is False


def test_recorded_native_history_input(tmp_path):
    fixture, limits, prior = scenario_recording("valid-native-fill")
    payload = recording_bytes(fixture)
    private = tmp_path / "synthetic-recording.json"
    private.write_bytes(payload)
    loaded = load_recording(private, hashlib.sha256(payload).hexdigest())
    assert loaded.provenance == "SIMULATION_ONLY"
    synthetic = asyncio.run(replay(loaded, limits=limits, prior=prior))
    assert synthetic.projection_ready and len(synthetic.fills) == 1
    assert not synthetic.provider_finality_proven and not synthetic.live_authority_granted
    path = os.environ.get("SENTINEL_NATIVE_RECORDING")
    expected = os.environ.get("SENTINEL_NATIVE_RECORDING_SHA256")
    if path is None and expected is None:
        return
    if path is None or expected is None:
        pytest.fail("EXPLICIT_PRIVATE_RECORDING_REQUIRED")
    recording = load_recording(Path(path), expected)
    batch = asyncio.run(replay(recording, limits=HistoryLimits(page_size=recording.page_size)))
    assert batch.traversal_exhausted
    assert not batch.provider_finality_proven and not batch.settlement_proven
    assert not batch.restore_grade_recovery_proven and not batch.live_authority_granted


def test_recording_hash_tamper_is_refused(tmp_path):
    recording, _limits, _prior = scenario_recording("empty-history")
    payload = recording_bytes(recording)
    path = tmp_path / "private.json"
    path.write_bytes(payload)
    assert load_recording(path, hashlib.sha256(payload).hexdigest()) == recording
    path.write_bytes(payload + b" ")
    with pytest.raises(ValueError, match="RECORDING_HASH_MISMATCH"):
        load_recording(path, hashlib.sha256(payload).hexdigest())


@pytest.mark.parametrize("amount_text", ["1.00000000000000000000001", "1", "1.0", "1E+3", "-0"])
def test_recorded_numeric_decimal_survives_native_wire_and_source_commitment(tmp_path, amount_text):
    from sentinel.execution.native_activity import activity_evidence
    from tests.support.native_activity_recording import cash_payload
    fixture, limits, _prior = scenario_recording("empty-history")
    amount = Decimal(amount_text)
    event = cash_payload("exact-numeric", net_amount=amount)
    exchanges = list(fixture.exchanges)
    exchanges[1] = exchanges[1].model_copy(update={"payload": [event]})
    recording = fixture.model_copy(update={"exchanges": tuple(exchanges)})
    payload = recording_bytes(recording)
    if amount_text == "1.00000000000000000000001":
        assert b'"net_amount":1.00000000000000000000001' in payload
    path = tmp_path / "exact-private.json"
    path.write_bytes(payload)
    loaded = load_recording(path, hashlib.sha256(payload).hexdigest())
    assert loaded.exchanges[1].payload[0]["net_amount"] == amount
    batch = asyncio.run(replay(loaded, limits=limits))
    assert batch.projection_ready and batch.cash_activities[0].net_amount == amount
    expected = activity_evidence(event, subject_sha256=fixture.subject.sha256)
    assert batch.evidence[0].payload_sha256 == expected.payload_sha256
    string_event = dict(event, net_amount=str(amount))
    assert expected.payload_sha256 != activity_evidence(string_event, subject_sha256=fixture.subject.sha256).payload_sha256
    assert activity_evidence(dict(event, net_amount=1), subject_sha256=fixture.subject.sha256).payload_sha256 != expected.payload_sha256


def test_recording_duplicate_fields_refuse_before_replay(tmp_path):
    fixture, _limits, _prior = scenario_recording("empty-history")
    payload = recording_bytes(fixture).replace(b'"provenance":"SIMULATION_ONLY"',
                                              b'"provenance":"SIMULATION_ONLY","provenance":"RECORDED_REPLAY"')
    path = tmp_path / "duplicate-private.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="DUPLICATE_RECORDING_FIELD"):
        load_recording(path, hashlib.sha256(payload).hexdigest())


@pytest.mark.parametrize("method", ["POST", "DELETE", "PATCH", "PUT"])
def test_recording_schema_forbids_mutations(method):
    with pytest.raises(ValidationError):
        RecordedExchange(method=method, path="/v2/account", payload={})


def test_replay_requires_exact_request_and_consumes_inventory():
    recording, _limits, _prior = scenario_recording("empty-history")
    transport = RecordingReplay(recording.exchanges, base_url=recording.subject.base_url)
    with pytest.raises(AssertionError, match="RECORDING_NOT_CONSUMED"):
        transport.assert_consumed()
    with pytest.raises(AssertionError, match="RECORDING_MUTATION_FORBIDDEN"):
        transport.handle(httpx.Request("POST", recording.subject.base_url + "/v2/account"))
    with pytest.raises(AssertionError, match="RECORDING_FIXTURE_CREDENTIALS_REQUIRED"):
        transport.handle(httpx.Request("GET", recording.subject.base_url + "/v2/account"))
