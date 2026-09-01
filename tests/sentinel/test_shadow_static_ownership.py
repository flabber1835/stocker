"""Shadow segment composition is static and independent of import order."""
from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from sentinel import shadow_runtime, shadow_segments


SESSION = "2026-08-25"
PUBLICATION_SHA = "a" * 64
SOURCE_SHA = "b" * 64
PREDECESSOR_SHA = "c" * 64


def test_shadow_runtime_has_one_static_segment_owner():
    assert (shadow_runtime.SegmentedPostgresShadowObservationStore
            is shadow_segments.SegmentedPostgresShadowObservationStore)
    assert (shadow_runtime._require_reviewed_genesis_publication.__module__
            == shadow_runtime.__name__)
    assert not hasattr(shadow_runtime, "_segment_runtime_installed")
    assert not hasattr(shadow_segments, "install_runtime_store")


def test_static_store_selects_the_active_segment_namespace(monkeypatch):
    expected_prefix = "shadow-observation:v1:primary:segment:00000002:"
    selected = SimpleNamespace(index=2, prefix=expected_prefix)
    conn = object()
    monkeypatch.setattr(
        shadow_segments, "active_segment",
        lambda actual, logical: (
            selected if actual is conn and logical == "primary"
            else pytest.fail("wrong active-segment lookup")))

    store = shadow_runtime.SegmentedPostgresShadowObservationStore(
        conn, observation_id="primary")

    assert store.segment is selected
    assert store.prefix == expected_prefix


@pytest.mark.parametrize("imports", [
    "from sentinel import shadow_runtime, shadow_segments",
    "from sentinel import shadow_service, shadow_runtime, shadow_segments",
    "from sentinel import shadow_runtime, shadow_recovery, shadow_segments",
    "from sentinel import dual_reconciliation, shadow_runtime, shadow_segments",
])
def test_shadow_owner_is_independent_of_import_order(imports):
    code = "\n".join([
        imports,
        "print(shadow_runtime.SegmentedPostgresShadowObservationStore "
        "is shadow_segments.SegmentedPostgresShadowObservationStore)",
        "print(shadow_runtime._require_reviewed_genesis_publication.__module__)",
        "print(hasattr(shadow_runtime, '_segment_runtime_installed'))",
        "print(hasattr(shadow_segments, 'install_runtime_store'))",
    ])
    result = subprocess.run(
        [sys.executable, "-c", code], check=False,
        capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "True", "sentinel.shadow_runtime", "False", "False"]


def test_segment_zero_without_reviewed_config_keeps_original_binding(
        monkeypatch):
    current = object()
    monkeypatch.setattr(
        shadow_runtime.feed_store, "latest_visible_session",
        lambda _conn: SESSION)
    monkeypatch.setattr(
        shadow_runtime, "_data_publication_subject_sha256",
        lambda actual, visible: (
            PUBLICATION_SHA
            if actual is current and visible == SESSION
            else pytest.fail("unexpected publication input")))

    assert shadow_runtime._require_reviewed_genesis_publication(
        object(), current=current, first_session=SESSION,
        runtime_identity={
            "validated_data_publication_sha256": PUBLICATION_SHA,
        }) is None

    with pytest.raises(
            shadow_runtime.ShadowRuntimeRefused,
            match="differs from the reviewed shadow genesis binding"):
        shadow_runtime._require_reviewed_genesis_publication(
            object(), current=current, first_session=SESSION,
            runtime_identity={
                "validated_data_publication_sha256": "0" * 64,
            })


def _segment(**changes):
    values = {
        "index": 1,
        "first_session": SESSION,
        "validated_source_identity_sha256": SOURCE_SHA,
        "new_data_publication_sha256": PUBLICATION_SHA,
        "predecessor_session": "2026-08-24",
        "predecessor_anchor_kind": "RUNTIME_AUTHORITY",
        "predecessor_anchor_sha256": PREDECESSOR_SHA,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _install_segment_gates(monkeypatch, *, segment=None, visible=SESSION,
                           publication_sha=PUBLICATION_SHA,
                           predecessor=None):
    selected = segment or _segment()
    prior = predecessor or (
        selected.predecessor_session,
        selected.predecessor_anchor_kind,
        selected.predecessor_anchor_sha256,
    )
    monkeypatch.setattr(
        shadow_runtime, "active_segment",
        lambda _conn, logical: (
            selected if logical == "primary"
            else pytest.fail("wrong logical observation")))
    monkeypatch.setattr(
        shadow_runtime.feed_store, "latest_visible_session",
        lambda _conn: visible)
    monkeypatch.setattr(
        shadow_runtime, "_data_publication_subject_sha256",
        lambda _current, _visible: publication_sha)
    monkeypatch.setattr(
        shadow_runtime, "predecessor_anchor",
        lambda _conn, logical, index: (
            prior if (logical, index) == ("primary", 0)
            else pytest.fail("wrong predecessor selection")))


def _reviewed_identity():
    return {
        "validated_source_identity_sha256": SOURCE_SHA,
        "reviewed_shadow_config": {"observation_id": "primary"},
    }


def test_later_segment_accepts_only_exact_marker_bindings(monkeypatch):
    _install_segment_gates(monkeypatch)

    assert shadow_runtime._require_reviewed_genesis_publication(
        object(), current=object(), first_session=SESSION,
        runtime_identity=_reviewed_identity()) is None


@pytest.mark.parametrize(
    ("changes", "gate_changes", "message"),
    [
        ({"first_session": "2026-08-24"}, {},
         "active segment first session differs"),
        ({}, {"source": "0" * 64},
         "segment source identity differs"),
        ({}, {"visible": "2026-08-24"},
         "segment genesis is not the exact live published frontier"),
        ({}, {"publication_sha": "0" * 64},
         "segment genesis publication differs"),
        ({}, {"predecessor": (
            "2026-08-24", "GENESIS", PREDECESSOR_SHA)},
         "segment predecessor state changed"),
    ],
)
def test_later_segment_mismatches_remain_fail_closed(
        monkeypatch, changes, gate_changes, message):
    segment = _segment(**changes)
    identity = _reviewed_identity()
    if "source" in gate_changes:
        identity["validated_source_identity_sha256"] = gate_changes["source"]
    _install_segment_gates(
        monkeypatch, segment=segment,
        visible=gate_changes.get("visible", SESSION),
        publication_sha=gate_changes.get("publication_sha", PUBLICATION_SHA),
        predecessor=gate_changes.get("predecessor"))

    with pytest.raises(shadow_segments.ShadowSegmentRefused, match=message):
        shadow_runtime._require_reviewed_genesis_publication(
            object(), current=object(), first_session=SESSION,
            runtime_identity=identity)
