from __future__ import annotations

from backtester.certification_metadata_completeness import (
    CertificationMetadataIncomplete,
    require_certification_metadata_complete,
)


def _manifest(**overrides):
    counts = {
        "unknown_security_type_observations": 0,
        "unknown_sector_observations": 0,
        "missing_active_metadata_observations": 0,
    }
    counts.update(overrides)
    return {"counts": counts}


def _fails(manifest, text: str) -> None:
    try:
        require_certification_metadata_complete(manifest)
    except CertificationMetadataIncomplete as exc:
        assert text in str(exc)
    else:
        raise AssertionError("incomplete metadata was accepted for certification")


def test_complete_metadata_passes():
    result = require_certification_metadata_complete(_manifest())
    assert result == {
        "unknown_security_type_observations": 0,
        "unknown_sector_observations": 0,
        "missing_active_metadata_observations": 0,
    }


def test_unknown_security_type_blocks_certification():
    _fails(
        _manifest(
            unknown_security_type_observations=7,
            missing_active_metadata_observations=7,
        ),
        "unknown_security_type_observations=7",
    )


def test_unknown_sector_blocks_certification():
    _fails(_manifest(unknown_sector_observations=11), "unknown_sector_observations=11")


def test_missing_counter_blocks_certification():
    manifest = _manifest()
    del manifest["counts"]["unknown_sector_observations"]
    _fails(manifest, "unknown_sector_observations")


def test_malformed_counter_blocks_certification():
    _fails(_manifest(unknown_sector_observations="0"), "non-negative integer")


def test_type_and_missing_active_counter_mismatch_blocks_certification():
    _fails(
        _manifest(
            unknown_security_type_observations=2,
            missing_active_metadata_observations=3,
        ),
        "internally inconsistent",
    )
