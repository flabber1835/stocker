from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import merge_historical_metadata_web_artifacts_v2_indexed as indexed


SOURCE_SHA = "a" * 40


def _artifact(shard: str, attempt: int, artifact_id: int) -> dict:
    return {
        "id": artifact_id,
        "name": f"metadata-v2-resilient-shard-{shard}-attempt-{attempt}-{SOURCE_SHA}",
        "expired": False,
    }


def test_select_latest_artifact_per_shard() -> None:
    selected = indexed.select_latest_artifacts(
        [
            _artifact("00", 1, 1),
            _artifact("00", 2, 2),
            _artifact("01", 1, 3),
        ],
        SOURCE_SHA,
        expected_shards=2,
    )
    assert selected["00"]["id"] == 2
    assert selected["01"]["id"] == 3


def test_select_latest_artifact_rejects_duplicate_latest_attempt() -> None:
    with pytest.raises(indexed.ArtifactSelectionError, match="duplicate latest artifact"):
        indexed.select_latest_artifacts(
            [
                _artifact("00", 2, 1),
                _artifact("00", 2, 2),
            ],
            SOURCE_SHA,
            expected_shards=1,
        )


def test_select_latest_artifact_rejects_missing_shard() -> None:
    with pytest.raises(indexed.ArtifactSelectionError, match="inventory mismatch"):
        indexed.select_latest_artifacts(
            [_artifact("00", 1, 1)],
            SOURCE_SHA,
            expected_shards=2,
        )


def test_verify_source_objects_hashes_retained_payload(tmp_path: Path) -> None:
    payload = b"authenticated SEC payload\n"
    member = "sources/example.txt"
    path = tmp_path / member
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    rows = [
        {
            "url": "https://www.sec.gov/example",
            "status": "200",
            "bytes": str(len(payload)),
            "artifact_member": member,
            "sha256": digest,
            "terminal_absence": "false",
        }
    ]
    assert indexed._verify_source_objects(tmp_path, rows) == 1
    path.write_bytes(b"tampered")
    with pytest.raises(base.ReconstructionError, match="hash mismatch"):
        indexed._verify_source_objects(tmp_path, rows)


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as fh:
        fh.writestr("../escape.txt", "bad")
    with pytest.raises(indexed.ArtifactSelectionError, match="path traversal"):
        indexed.safe_extract(archive, tmp_path / "out")
