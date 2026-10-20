"""Independent canonical-byte oracles for verification-local JSON encoding."""
from datetime import date
from decimal import Decimal
import gc
import hashlib
import inspect
import json
import sys
import textwrap
from types import SimpleNamespace
import weakref

import pytest

from sentinel.feed import rolling_store as store
from sentinel.feed.rolling_contract import (
    CanonicalBar, CanonicalBenchmark, RestartRequirement, canonical_json, digest,
)
from tests.sentinel.test_rolling_snapshot_storage import conn, pg, window  # noqa: F401


OPTIONS = dict(sort_keys=True, separators=(",", ":"),
               ensure_ascii=True, allow_nan=False)


class RecordingHash:
    def __init__(self):
        self.updates = []

    def update(self, value):
        self.updates.append(value)


def oracle_bytes(value):
    # Do not use _fold or its encoder factory: both seal and verification could
    # otherwise agree on the same accidentally changed serialization.
    return canonical_json(value).encode("ascii") + b"\n"


def oracle_hash(values):
    result = hashlib.sha256()
    for value in values:
        result.update(oracle_bytes(value))
    return result.hexdigest()


def assert_encoding(value, encoder):
    actual = RecordingHash()
    store._fold(actual, value, encoder)
    expected = oracle_bytes(value)
    assert b"".join(actual.updates) == expected
    assert actual.updates == [expected[:-1], b"\n"]


@pytest.mark.parametrize("value", [
    None, True, False, 0, 10**100, -(10**100), 0.0, -0.0, 1.25,
    1e-7, 5e-324, sys.float_info.max,
    "caf\u00e9 \U0001f600", "lone surrogate \ud800", "\x00\n\r\t\\\"",
    (), ("2026-10-19", "CAF\u00c9\U0001f600"),
    {"z": [None, False, (1, -0.0)], "a": "\u00e9"},
    {2: "two", 1: "one"}, {None: "null key"}, {False: "bool key"},
    {1.5: "float key"},
])
def test_local_encoder_preserves_exact_canonical_bytes(value):
    assert_encoding(value, json.JSONEncoder(**OPTIONS))


def test_model_payloads_and_key_order_preserve_bytes():
    bar = CanonicalBar(
        security_id="CAF\u00c9\U0001f600", session=date(2026, 10, 19), ticker="\u00c9",
        close_signal=1e-7, close_unadjusted=1.25, open_unadjusted=None,
        volume=0.0, split_ratio=1.0, dividend_per_share=0.0)
    benchmark = CanonicalBenchmark(
        session=bar.session, spy_total_return=sys.float_info.max,
        bil_open_signal=None, bil_close_signal=1.25,
        bil_close_adjusted=None, bil_close_unadjusted=1.0)
    encoder = json.JSONEncoder(**OPTIONS)
    for value in (bar.model_dump(mode="json"), benchmark.model_dump(mode="json")):
        assert_encoding(value, encoder)
        reversed_keys = dict(reversed(tuple(value.items())))
        assert oracle_bytes(reversed_keys) == oracle_bytes(value)
        assert_encoding(reversed_keys, encoder)


def circular_value():
    result = []
    result.append(result)
    return result


@pytest.mark.parametrize("make", [
    lambda: float("nan"), lambda: float("inf"), lambda: -float("inf"),
    lambda: {"early": 1, "late": float("nan")},
    lambda: Decimal("1.00"), lambda: date(2026, 10, 19),
    lambda: b"bytes", lambda: object(), lambda: frozenset({1}),
    lambda: {(1, 2): "unsupported key"}, lambda: {"a": 1, 2: "mixed keys"},
    circular_value,
])
def test_encoding_failure_preserves_error_and_untouched_hash(make):
    value = make()
    with pytest.raises((TypeError, ValueError)) as expected:
        canonical_json(value)
    encoder = json.JSONEncoder(**OPTIONS)
    actual = RecordingHash()
    with pytest.raises(type(expected.value)) as observed:
        store._fold(actual, value, encoder)
    assert str(observed.value) == str(expected.value)
    assert not actual.updates
    assert_encoding({"valid after error": "\u00e9"}, encoder)


def test_default_fold_still_uses_canonical_json(monkeypatch):
    calls = []

    def canonical(value):
        calls.append(value)
        return '"default canonical path"'

    monkeypatch.setattr(store, "canonical_json", canonical)
    output = RecordingHash()
    value = {"row": 1}
    store._fold(output, value)
    assert calls == [value]
    assert output.updates == [b'"default canonical path"', b"\n"]


def test_encoder_keeps_no_row_or_error_graph_and_observes_mutation():
    class Payload(dict):
        pass

    encoder = json.JSONEncoder(**OPTIONS)
    payload = Payload(value=1)
    first = RecordingHash()
    store._fold(first, payload, encoder)
    payload["value"] = 2
    second = RecordingHash()
    store._fold(second, payload, encoder)
    assert first.updates != second.updates
    assert b"".join(second.updates) == oracle_bytes(payload)
    reference = weakref.ref(payload)
    del payload
    gc.collect()
    assert reference() is None

    def fail_without_retaining_traceback():
        row = Payload()
        row["cycle"] = row
        reference = weakref.ref(row)
        try:
            store._fold(RecordingHash(), row, encoder)
        except ValueError:
            pass
        else:
            pytest.fail("circular JSON must refuse")
        return reference

    reference = fail_without_retaining_traceback()
    gc.collect()
    assert reference() is None
    assert_encoding({"valid after released error": 1}, encoder)


@pytest.mark.parametrize("changed", [
    {"ensure_ascii": False}, {"sort_keys": False},
    {"separators": (", ", ": ")},
])
def test_changed_encoding_options_falsify_byte_oracle(changed):
    encoder = json.JSONEncoder(**{**OPTIONS, **changed})
    with pytest.raises((AssertionError, UnicodeEncodeError)):
        assert_encoding({"z": "\u00e9", "a": [1, 2]}, encoder)


def sealed_input(conn, window):
    candidate = store.begin(
        conn, window=window,
        reference_sha256=store.put_evidence(conn, {"reference": "\u00e9"}),
        source_evidence_sha256=store.put_evidence(conn, {"source": "fixture"}),
        expected_publication_version=None, dependencies_sha256=digest({}))
    bars = [CanonicalBar(
        security_id=sid, session=day, ticker=sid,
        close_signal=1e-7, close_unadjusted=1.25, open_unadjusted=None,
        volume=0.0, split_ratio=1.0, dividend_per_share=0.0)
        for day in window.sessions for sid in ("ASCII", "CAF\u00c9\U0001f600")]
    benchmarks = [CanonicalBenchmark(
        session=day, spy_total_return=600.25, bil_open_signal=None,
        bil_close_signal=91.5, bil_close_adjusted=None,
        bil_close_unadjusted=91.0) for day in window.sessions]
    expected = {
        "bars_sha256": oracle_hash(row.model_dump(mode="json") for row in bars),
        "coverage_sha256": oracle_hash((str(row.session), row.security_id) for row in bars),
        "benchmarks_sha256": oracle_hash(row.model_dump(mode="json") for row in benchmarks),
    }
    store.write_bars(conn, candidate, bars)
    store.write_benchmarks(conn, candidate, benchmarks)
    manifest = store.seal(
        conn, candidate,
        expected_keys=((str(row.session), row.security_id) for row in bars),
        normalization_version="hash-encoding-fixture/1", requirements=RestartRequirement())
    for field, value in expected.items():
        assert getattr(manifest, field) == value
    assert manifest.snapshot_id == digest(manifest.model_dump(mode="json"))
    conn.commit()
    return candidate, manifest


def test_seal_and_full_verification_match_independent_hashes(conn, window, monkeypatch):
    def forbidden_encoder(**_options):
        raise AssertionError("sealing must retain canonical_json")

    # Replace only rolling_store's module reference; the independent canonical
    # oracle retains the original stdlib json module and JSONEncoder.
    monkeypatch.setattr(store, "json", SimpleNamespace(
        JSONEncoder=forbidden_encoder, loads=json.loads))
    candidate, expected = sealed_input(conn, window)
    created = []

    def tracked_encoder(**options):
        assert options == OPTIONS
        encoder = json.JSONEncoder(**options)
        created.append(weakref.ref(encoder))
        return encoder

    monkeypatch.setattr(store, "json", SimpleNamespace(
        JSONEncoder=tracked_encoder, loads=json.loads))
    for number in (1, 2):
        completed = store._verify_content_uncached(conn, candidate)
        assert completed.manifest == expected
        assert completed.readiness is None
        assert len(created) == number
        gc.collect()
        assert all(reference() is None for reference in created)


def test_changed_encoder_fails_existing_full_manifest_hash(conn, window, monkeypatch):
    candidate, _ = sealed_input(conn, window)

    def altered_encoder(**options):
        return json.JSONEncoder(**{**options, "separators": (", ", ": ")})

    monkeypatch.setattr(store, "json", SimpleNamespace(
        JSONEncoder=altered_encoder, loads=json.loads))
    with pytest.raises(store.SnapshotStorageRefused, match="content differs"):
        store._verify_content_uncached(conn, candidate)


def corrupt_final_bar(conn, candidate, window):
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        result = conn.execute(
            "UPDATE sentinel_snapshot_bars SET close_unadjusted=close_unadjusted+1 "
            "WHERE candidate_id=%s AND session=%s AND security_id=%s",
            (candidate, window.end, "CAF\u00c9\U0001f600"))
        assert result.rowcount == 1
    conn.commit()


def require_corruption_refused(conn, candidate):
    with pytest.raises(store.SnapshotStorageRefused, match="content differs"):
        store._verify_content_uncached(conn, candidate)


def test_full_verification_still_refuses_final_row_corruption(conn, window):
    candidate, _ = sealed_input(conn, window)
    corrupt_final_bar(conn, candidate, window)
    require_corruption_refused(conn, candidate)


def test_removed_content_hash_guard_is_falsified(conn, window, monkeypatch):
    candidate, _ = sealed_input(conn, window)
    corrupt_final_bar(conn, candidate, window)
    source = textwrap.dedent(inspect.getsource(store._verify_content_uncached))
    marker = "or bars_hash.hexdigest() != value.bars_sha256"
    assert marker in source
    namespace = {}
    exec(compile(source.replace(marker, "or False"), "hash-guard-falsifier", "exec"),
         store.__dict__, namespace)
    monkeypatch.setattr(store, "_verify_content_uncached", namespace["_verify_content_uncached"])
    with pytest.raises(pytest.fail.Exception):
        require_corruption_refused(conn, candidate)
