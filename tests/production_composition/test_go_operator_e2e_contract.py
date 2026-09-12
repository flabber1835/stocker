from __future__ import annotations

import pytest

from tools import production_go_e2e_support as e2e


def _handoff(commit: str, runtime_id: str, test_id: str) -> dict:
    return {
        "schema": "sentinel.validated-artifact-handoff/3",
        "mode": "LOCAL_FULL_CERTIFICATION",
        "git_commit": commit,
        "runtime_local_image_id": runtime_id,
        "test_lens_local_image_id": test_id,
    }


def _ordinary(commit: str, runtime_id: str) -> dict:
    return {
        "git_commit": commit,
        "ordinary_runtime_image_digest": runtime_id,
    }


def test_complete_operator_lifecycle_transcript_is_accepted():
    e2e.validate_lifecycle_transcript("\n".join(e2e.LIFECYCLE_MARKERS))


@pytest.mark.parametrize("missing", e2e.LIFECYCLE_MARKERS)
def test_every_major_operator_stage_is_mandatory(missing):
    text = "\n".join(
        marker for marker in e2e.LIFECYCLE_MARKERS if marker != missing)
    with pytest.raises(e2e.E2ERefused, match="lifecycle marker missing"):
        e2e.validate_lifecycle_transcript(text)


def test_lifecycle_markers_must_remain_in_production_order():
    markers = list(e2e.LIFECYCLE_MARKERS)
    markers[5], markers[6] = markers[6], markers[5]
    with pytest.raises(e2e.E2ERefused, match="lifecycle marker missing"):
        e2e.validate_lifecycle_transcript("\n".join(markers))


def test_commit_image_and_pointer_authority_must_converge():
    commit = "a" * 40
    runtime_id = "sha256:" + "b" * 64
    test_id = "sha256:" + "c" * 64
    assert e2e.validate_authority_payloads(
        handoff=_handoff(commit, runtime_id, test_id),
        ordinary=_ordinary(commit, runtime_id),
        pointer=f"SENTINEL_RUNTIME_IMAGE_REF={runtime_id}",
        commit=commit,
    ) == (runtime_id, test_id)


@pytest.mark.parametrize(
    "mutation",
    ("handoff_commit", "ordinary_commit", "ordinary_runtime", "pointer"),
)
def test_any_cross_stage_authority_break_refuses(mutation):
    commit = "a" * 40
    runtime_id = "sha256:" + "b" * 64
    test_id = "sha256:" + "c" * 64
    handoff = _handoff(commit, runtime_id, test_id)
    ordinary = _ordinary(commit, runtime_id)
    pointer = f"SENTINEL_RUNTIME_IMAGE_REF={runtime_id}"

    if mutation == "handoff_commit":
        handoff["git_commit"] = "d" * 40
    elif mutation == "ordinary_commit":
        ordinary["git_commit"] = "d" * 40
    elif mutation == "ordinary_runtime":
        ordinary["ordinary_runtime_image_digest"] = "sha256:" + "d" * 64
    elif mutation == "pointer":
        pointer = "SENTINEL_RUNTIME_IMAGE_REF=sha256:" + "d" * 64

    with pytest.raises(e2e.E2ERefused):
        e2e.validate_authority_payloads(
            handoff=handoff, ordinary=ordinary, pointer=pointer, commit=commit)
