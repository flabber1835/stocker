#!/usr/bin/env python3
"""Logically merge authenticated SEC shard artifacts without materializing raw source bytes together.

This recovery-oriented merger is intentionally orchestration-only. It selects the
latest artifact for each shard from one pinned GitHub Actions run, downloads one
artifact at a time, verifies the artifact digest, shard checksums, PASS coverage,
and every retained raw SEC source object hash, then discards the raw object bytes.
Only the normalized evidence tables plus an authenticated artifact index are kept
in the merged output. This avoids exceeding the 14 GB disk limit of standard
GitHub-hosted Linux runners while preserving exact provenance for every source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import merge_historical_metadata_web_shards_v2 as canonical_merge

SCHEMA = "backtester.historical-metadata-reconstruction-v2.web-artifact-index-merge/1"
ARTIFACT_INDEX_SCHEMA = "backtester.historical-metadata-reconstruction-v2.web-shard-artifact-index/1"
API_VERSION = "2022-11-28"


class ArtifactSelectionError(base.ReconstructionError):
    pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _api_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "stocker-metadata-v2-indexed-merge",
    }


def _read_json(url: str, token: str) -> tuple[dict, Mapping[str, str]]:
    request = urllib.request.Request(url, headers=_api_headers(token))
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return payload, dict(response.headers.items())


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        match = re.match(r"<([^>]+)>", section)
        if match:
            return match.group(1)
    return None


def list_run_artifacts(repository: str, run_id: int, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100"
    artifacts: list[dict] = []
    while url:
        payload, headers = _read_json(url, token)
        batch = payload.get("artifacts")
        if not isinstance(batch, list):
            raise ArtifactSelectionError("GitHub artifact response lacks artifacts list")
        artifacts.extend(dict(item) for item in batch)
        url = _next_link(headers.get("Link") or headers.get("link"))
    return artifacts


def select_latest_artifacts(
    artifacts: Sequence[Mapping[str, object]],
    source_run_sha: str,
    expected_shards: int = 32,
) -> dict[str, dict]:
    pattern = re.compile(
        rf"^metadata-v2-resilient-shard-(\d{{2}})-attempt-(\d+)-{re.escape(source_run_sha)}$"
    )
    choices: dict[str, list[tuple[int, int, dict]]] = {}
    for raw in artifacts:
        artifact = dict(raw)
        if bool(artifact.get("expired")):
            continue
        name = str(artifact.get("name") or "")
        match = pattern.fullmatch(name)
        if not match:
            continue
        shard, attempt_text = match.groups()
        try:
            attempt = int(attempt_text)
            artifact_id = int(artifact.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if artifact_id <= 0:
            continue
        choices.setdefault(shard, []).append((attempt, artifact_id, artifact))

    expected = {f"{index:02d}" for index in range(expected_shards)}
    actual = set(choices)
    if actual != expected:
        raise ArtifactSelectionError(
            f"artifact shard inventory mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}"
        )

    selected: dict[str, dict] = {}
    for shard in sorted(expected):
        highest_attempt = max(item[0] for item in choices[shard])
        winners = [item for item in choices[shard] if item[0] == highest_attempt]
        if len(winners) != 1:
            ids = [item[1] for item in winners]
            raise ArtifactSelectionError(
                f"duplicate latest artifact for shard {shard} attempt {highest_attempt}: ids={ids}"
            )
        selected[shard] = winners[0][2]
    return selected


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _artifact_blob_url(archive_url: str, token: str) -> str:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(archive_url, headers=_api_headers(token))
    try:
        opener.open(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise
        location = exc.headers.get("Location")
        if not location:
            raise ArtifactSelectionError(f"artifact redirect missing Location for {archive_url}")
        return location
    raise ArtifactSelectionError(f"artifact download endpoint did not redirect: {archive_url}")


def download_artifact(artifact: Mapping[str, object], token: str, target: Path) -> str:
    archive_url = str(artifact.get("archive_download_url") or "")
    if not archive_url:
        raise ArtifactSelectionError(f"artifact lacks archive_download_url: {artifact.get('name')}")
    blob_url = _artifact_blob_url(archive_url, token)
    request = urllib.request.Request(
        blob_url,
        headers={"User-Agent": "stocker-metadata-v2-indexed-merge"},
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=300) as response, target.open("wb") as fh:
        while True:
            chunk = response.read(8 * 1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            digest.update(chunk)
    actual = digest.hexdigest()
    expected = str(artifact.get("digest") or "")
    if expected.startswith("sha256:") and actual != expected.split(":", 1)[1]:
        raise ArtifactSelectionError(
            f"artifact archive digest mismatch for {artifact.get('name')}: expected={expected} actual=sha256:{actual}"
        )
    return actual


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved_root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ArtifactSelectionError(f"refusing symlink in artifact: {info.filename}")
            target = (destination / info.filename).resolve()
            if target != resolved_root and resolved_root not in target.parents:
                raise ArtifactSelectionError(f"artifact path traversal: {info.filename}")
        archive.extractall(destination)


def _load_rows(shard_dir: Path, name: str) -> list[dict[str, str]]:
    path = shard_dir / name
    return base.read_gzip_csv(path) if path.exists() else []


def _verify_source_objects(shard_dir: Path, source_rows: Sequence[Mapping[str, object]]) -> int:
    verified = 0
    for row in source_rows:
        member = str(row.get("artifact_member") or "")
        digest = str(row.get("sha256") or "")
        terminal = str(row.get("terminal_absence") or "").lower() in {"true", "1"}
        if not member:
            if terminal:
                continue
            try:
                status_code = str(row.get("status") or "")
                byte_count = int(row.get("bytes") or 0)
            except (TypeError, ValueError):
                byte_count = 0
                status_code = str(row.get("status") or "")
            if status_code == "200" and byte_count > 0:
                raise base.ReconstructionError(
                    f"source manifest row lacks artifact member: {row.get('url')}"
                )
            continue
        path = shard_dir / member
        if not path.is_file():
            raise base.ReconstructionError(f"shard source object missing: {member}")
        if digest and _sha256_file(path) != digest:
            raise base.ReconstructionError(f"shard source object hash mismatch: {member}")
        verified += 1
    return verified


def _find_shard_root(extracted: Path) -> Path:
    matches = list(extracted.rglob("shard_runner_coverage.json"))
    if len(matches) != 1:
        raise ArtifactSelectionError(
            f"artifact must contain exactly one shard_runner_coverage.json; found={len(matches)}"
        )
    return matches[0].parent


def merge_from_run(
    repository: str,
    run_id: int,
    source_run_sha: str,
    token: str,
    output: Path,
    expected_shards: int = 32,
) -> dict:
    artifacts = list_run_artifacts(repository, run_id, token)
    selected = select_latest_artifacts(artifacts, source_run_sha, expected_shards)

    source_rows: list[dict[str, str]] = []
    identity_rows: list[dict[str, str]] = []
    type_rows: list[dict[str, str]] = []
    rejected_rows: list[dict[str, str]] = []
    sic_rows: list[dict[str, str]] = []
    transport = Counter()
    terminal_absences = 0
    planned_ciks = 0
    completed_ciks = 0
    verified_source_objects = 0
    selected_attempts: dict[str, int] = {}
    artifact_records: list[dict[str, object]] = []

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="metadata-v2-shard-") as temp_root_text:
        temp_root = Path(temp_root_text)
        for index in range(expected_shards):
            shard = f"{index:02d}"
            artifact = selected[shard]
            name = str(artifact.get("name") or "")
            attempt_match = re.search(r"-attempt-(\d+)-", name)
            if not attempt_match:
                raise ArtifactSelectionError(f"cannot parse attempt from artifact name: {name}")
            attempt = int(attempt_match.group(1))
            selected_attempts[shard] = attempt

            zip_path = temp_root / f"{shard}.zip"
            extracted = temp_root / f"{shard}-extracted"
            archive_sha256 = download_artifact(artifact, token, zip_path)
            safe_extract(zip_path, extracted)
            shard_dir = _find_shard_root(extracted)

            base.verify_checksums(shard_dir)
            runner = json.loads((shard_dir / "shard_runner_coverage.json").read_text(encoding="utf-8"))
            if runner.get("status") != "PASS" or str(runner.get("shard") or "") != shard:
                raise base.ReconstructionError(
                    f"latest shard artifact is not authoritative PASS for shard {shard}: {name}"
                )
            web = json.loads((shard_dir / "web_coverage.json").read_text(encoding="utf-8"))
            if web.get("status") != "PASS" or not web.get("complete"):
                raise base.ReconstructionError(f"latest shard artifact is not transport-complete: {name}")
            if int(web.get("completed_unique_ciks") or 0) != int(web.get("planned_unique_ciks") or 0):
                raise base.ReconstructionError(f"latest shard artifact has incomplete CIK coverage: {name}")

            shard_source_rows = _load_rows(shard_dir, "web_source_manifest.csv.gz")
            verified_source_objects += _verify_source_objects(shard_dir, shard_source_rows)
            source_rows.extend(shard_source_rows)
            identity_rows.extend(_load_rows(shard_dir, "web_identity_sources.csv.gz"))
            type_rows.extend(_load_rows(shard_dir, "web_security_type_sources.csv.gz"))
            rejected_rows.extend(_load_rows(shard_dir, "web_security_type_rejected.csv.gz"))
            sic_rows.extend(_load_rows(shard_dir, "web_sic_sources.csv.gz"))

            planned_ciks += int(web.get("planned_unique_ciks") or 0)
            completed_ciks += int(web.get("completed_unique_ciks") or 0)
            terminal_absences += int(
                web.get("terminal_source_absences")
                or (web.get("transport") or {}).get("terminal_absences")
                or 0
            )
            for key, value in (web.get("transport") or {}).items():
                try:
                    transport[str(key)] += int(value)
                except (TypeError, ValueError):
                    pass

            artifact_records.append(
                {
                    "shard": shard,
                    "attempt": attempt,
                    "artifact_id": int(artifact.get("id") or 0),
                    "name": name,
                    "size_in_bytes": int(artifact.get("size_in_bytes") or 0),
                    "github_digest": str(artifact.get("digest") or ""),
                    "downloaded_archive_sha256": archive_sha256,
                    "created_at": str(artifact.get("created_at") or ""),
                    "expires_at": str(artifact.get("expires_at") or ""),
                    "shard_checksum_manifest_sha256": _sha256_file(shard_dir / "SHA256SUMS.txt"),
                    "web_coverage_sha256": _sha256_file(shard_dir / "web_coverage.json"),
                    "runner_coverage_sha256": _sha256_file(shard_dir / "shard_runner_coverage.json"),
                    "source_manifest_sha256": _sha256_file(shard_dir / "web_source_manifest.csv.gz"),
                }
            )
            print(
                f"[INDEX MERGE] shard={index+1}/{expected_shards} pct={(index+1)*100.0/expected_shards:.1f}% "
                f"selected_attempt={attempt} artifact_id={artifact.get('id')} "
                f"planned_ciks={planned_ciks} completed_ciks={completed_ciks} "
                f"verified_source_objects={verified_source_objects}",
                flush=True,
            )

            zip_path.unlink(missing_ok=True)
            shutil.rmtree(extracted, ignore_errors=True)

    source_rows = canonical_merge._dedup(
        source_rows, ("url", "status", "sha256", "artifact_member")
    )
    identity_rows = canonical_merge._dedup(
        identity_rows,
        ("security_id_hint", "filed", "cik", "accession", "sec_symbol", "source_sha256"),
    )
    type_rows = canonical_merge._dedup(
        type_rows,
        ("security_id_hint", "filed", "cik", "accession", "classification", "source_sha256"),
    )
    rejected_rows = canonical_merge._dedup(
        rejected_rows,
        (
            "security_id_hint",
            "filed",
            "cik",
            "accession",
            "classification",
            "source_sha256",
            "reason",
        ),
    )
    sic_rows = canonical_merge._dedup(
        sic_rows, ("filed", "cik", "sic", "accession", "source_sha256")
    )

    base.write_gzip_csv(
        output / "web_source_manifest.csv.gz",
        [
            "url",
            "status",
            "path",
            "sha256",
            "bytes",
            "attempts",
            "terminal_absence",
            "retrieved_at",
            "artifact_member",
        ],
        source_rows,
    )
    base.write_gzip_csv(
        output / "web_identity_sources.csv.gz",
        [
            "security_id_hint",
            "accession",
            "filed",
            "cik",
            "sec_symbol",
            "document_type",
            "source_kind",
            "source_url",
            "source_sha256",
        ],
        identity_rows,
    )
    base.write_gzip_csv(
        output / "web_security_type_sources.csv.gz",
        [
            "security_id_hint",
            "accession",
            "filed",
            "cik",
            "sec_symbol",
            "document_type",
            "classification",
            "security_title_evidence",
            "authority",
            "source_url",
            "source_sha256",
        ],
        type_rows,
    )
    base.write_gzip_csv(
        output / "web_security_type_rejected.csv.gz",
        [
            "security_id_hint",
            "accession",
            "filed",
            "cik",
            "sec_symbol",
            "document_type",
            "classification",
            "reason",
            "source_url",
            "source_sha256",
        ],
        rejected_rows,
    )
    base.write_gzip_csv(
        output / "web_sic_sources.csv.gz",
        ["filed", "cik", "sic", "source_kind", "accession", "source_url", "source_sha256"],
        sic_rows,
    )

    artifact_index = {
        "schema": ARTIFACT_INDEX_SCHEMA,
        "status": "PASS",
        "repository": repository,
        "source_run_id": run_id,
        "source_run_sha": source_run_sha,
        "selection_rule": "highest non-expired attempt per shard; selected artifact must itself verify PASS and complete",
        "expected_shards": expected_shards,
        "artifacts": artifact_records,
    }
    artifact_index_path = output / "web_shard_artifact_index.json"
    artifact_index_path.write_text(
        json.dumps(artifact_index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    normalized_hash = base.normalized_web_evidence_hash(identity_rows, type_rows, sic_rows)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "complete": completed_ciks == planned_ciks,
        "expected_shards": expected_shards,
        "merged_shards": len(artifact_records),
        "selected_attempts": selected_attempts,
        "planned_unique_ciks": planned_ciks,
        "completed_unique_ciks": completed_ciks,
        "terminal_source_absences": terminal_absences,
        "transport": dict(transport),
        "source_manifest_rows": len(source_rows),
        "identity_sources": len(identity_rows),
        "admitted_security_type_sources": len(type_rows),
        "rejected_security_type_sources": len(rejected_rows),
        "sic_sources": len(sic_rows),
        "normalized_evidence_sha256": normalized_hash,
        "verified_raw_source_objects": verified_source_objects,
        "raw_source_objects_embedded": False,
        "raw_source_payload_mode": "verified_sharded_github_actions_artifacts",
        "artifact_index_sha256": _sha256_file(artifact_index_path),
        "partitioning": "stable validated CIK hash shards; source payload remains sharded to respect standard-runner disk bounds",
    }
    if not summary["complete"] or summary["merged_shards"] != expected_shards:
        raise base.ReconstructionError("indexed web corpus is incomplete")
    (output / "web_coverage.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    base.write_checksums(output)
    base.verify_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--source-run-sha", required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, default=32)
    args = parser.parse_args()
    if not args.repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")
    token = os.environ.get(args.token_env, "")
    if not token:
        parser.error(f"missing token environment variable: {args.token_env}")
    result = merge_from_run(
        args.repository,
        args.run_id,
        args.source_run_sha,
        token,
        args.output,
        args.expected_shards,
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
