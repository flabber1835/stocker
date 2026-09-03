#!/usr/bin/env python3
"""Build canonical PIT dataset /2 with guarded historical-metadata V2 overlay."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from backtester import canonical_pit_dataset as canonical
from backtester.canonical_pit_metadata_v2 import (
    HistoricalMetadataV2Authority,
    sha256_file,
)


def _rewrite_manifest(
    output: Path,
    authority: HistoricalMetadataV2Authority,
    metadata_pointer: Path,
) -> dict:
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != canonical.SCHEMA:
        raise RuntimeError("canonical builder did not emit current dataset schema")

    pointer = json.loads(Path(metadata_pointer).read_text(encoding="utf-8"))
    package = str(pointer.get("package") or "")
    if not package.startswith(
        "ghcr.io/flabber1835/stocker-historical-metadata-v2@sha256:"
    ):
        raise RuntimeError("historical metadata V2 pointer is not digest-pinned")
    if pointer.get("timeline_status") != "PASS":
        raise RuntimeError("historical metadata V2 pointer is not timeline PASS")

    provenance = authority.provenance()
    provenance.update(
        {
            "pointer_sha256": sha256_file(Path(metadata_pointer)),
            "package": package,
            "source_sha": str(pointer.get("source_sha") or ""),
            "workflow_run_id": str(pointer.get("workflow_run_id") or ""),
        }
    )
    manifest["historical_metadata_v2"] = provenance
    manifest.setdefault("field_authorities", {}).update(
        {
            "issuer": (
                "guarded metadata V2 strict-prior CIK when available; "
                "legacy strict-prior SEC CIK otherwise; unknown security singleton"
            ),
            "security_type": (
                "guarded metadata V2 strict-prior security-title evidence when "
                "available; legacy strict-prior SEC/EDGAR positive evidence otherwise; "
                "unknown ineligible"
            ),
            "sector": (
                "guarded metadata V2 strict-prior SIC when available; otherwise "
                "legacy strict-prior SEC CIK -> SIC; frozen FF12"
            ),
        }
    )
    manifest["reconstruction_overlay_module_sha256"] = sha256_file(Path(__file__))
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    sums_path = output / "SHA256SUMS.txt"
    lines = []
    found_manifest = False
    for raw in sums_path.read_text(encoding="utf-8").splitlines():
        parts = raw.split()
        if len(parts) != 2:
            raise RuntimeError("canonical SHA256SUMS.txt contains malformed row")
        name = parts[1].lstrip("*")
        if name == "manifest.json":
            lines.append(f"{sha256_file(manifest_path)}  manifest.json")
            found_manifest = True
        else:
            lines.append(raw)
    if not found_manifest:
        lines.append(f"{sha256_file(manifest_path)}  manifest.json")
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    validated = canonical.CanonicalPITDataset(output)
    if validated.dataset_hash != manifest["dataset_hash"]:
        raise RuntimeError("post-overlay canonical dataset hash changed unexpectedly")
    return manifest


def build(
    *,
    output: Path,
    metadata_v2: Path,
    metadata_pointer: Path,
    warmup_start: str,
    measurement_start: str,
    end: str,
    root: Path,
) -> dict:
    authority = HistoricalMetadataV2Authority(metadata_v2)
    original = canonical._metadata_record

    def merged_record(
        model,
        issuer_authority,
        type_authority,
        sid,
        ticker,
        session,
        listing_first_session,
        ff12_for_sic,
    ):
        legacy = original(
            model,
            issuer_authority,
            type_authority,
            sid,
            ticker,
            session,
            listing_first_session,
            ff12_for_sic,
        )
        return authority.apply(
            security_id=str(sid),
            ticker=str(ticker),
            session=str(session),
            legacy=legacy,
            type_authority=type_authority,
            ff12_for_sic=ff12_for_sic,
        )

    canonical._metadata_record = merged_record
    try:
        manifest = canonical.build_dataset(
            output=output,
            start=warmup_start,
            measurement_start=measurement_start,
            end=end,
            root=root,
        )
    finally:
        canonical._metadata_record = original

    if manifest.get("schema") != "backtester.canonical-pit-dataset/2":
        raise RuntimeError("historical metadata V2 build requires canonical dataset /2")
    return _rewrite_manifest(output, authority, metadata_pointer)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-v2", type=Path, required=True)
    parser.add_argument("--metadata-pointer", type=Path, required=True)
    parser.add_argument("--warmup-start", required=True)
    parser.add_argument("--measurement-start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"canonical output is not empty: {args.output}")
    os.environ.setdefault("BACKTESTER_BRANCH_SHA", os.environ.get("GITHUB_SHA", ""))
    manifest = build(
        output=args.output,
        metadata_v2=args.metadata_v2,
        metadata_pointer=args.metadata_pointer,
        warmup_start=args.warmup_start,
        measurement_start=args.measurement_start,
        end=args.end,
        root=args.root.resolve(),
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "schema": manifest["schema"],
                "dataset_hash": manifest["dataset_hash"],
                "window": manifest["window"],
                "counts": manifest["counts"],
                "historical_metadata_v2": manifest["historical_metadata_v2"],
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
