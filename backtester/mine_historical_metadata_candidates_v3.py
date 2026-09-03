#!/usr/bin/env python3
"""Mine additional historical-metadata evidence from the already-frozen SEC corpus.

This is deliberately a candidate miner, not an admission path. It never changes
canonical metadata or converts an unresolved episode to eligible/ineligible. The
output is provenance-rich evidence for a later authority review.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

SCHEMA = "backtester.historical-metadata-reconstruction-v3.candidate-mine/1"
MERGE_SCHEMA = "backtester.historical-metadata-reconstruction-v3.candidate-merge/1"

CIK_SUBMISSION_RE = re.compile(r"/submissions/CIK(\d{10})\.json(?:$|\?)", re.I)
CIK_ARCHIVE_RE = re.compile(r"/Archives/edgar/data/(\d+)(?:/|$)", re.I)
FORM_RE = re.compile(r"CONFORMED\s+SUBMISSION\s+TYPE\s*:\s*([^\r\n<]+)", re.I)
FILED_RE = re.compile(r"FILED\s+AS\s+OF\s+DATE\s*:\s*(\d{8})", re.I)
ACCESSION_RE = re.compile(r"ACCESSION\s+NUMBER\s*:\s*([0-9-]+)", re.I)
SIC_RE = re.compile(
    r"STANDARD\s+INDUSTRIAL\s+CLASSIFICATION\s*:\s*[^\[]*\[(\d{3,4})\]",
    re.I,
)
ISSUER_TRADING_SYMBOL_RE = re.compile(
    r"<issuerTradingSymbol[^>]*>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</issuerTradingSymbol>",
    re.I | re.S,
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

CURRENT_AUTHORITY_FORMS = {
    "10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A",
    "8-K", "8-K/A", "S-1", "S-1/A", "F-1", "F-1/A", "10", "10/A",
}
# These are intentionally candidates only. Their presence is not authority until
# a separate review explicitly approves a form/evidence contract.
EXTENDED_CANDIDATE_FORMS = {
    "6-K", "6-K/A", "S-3", "S-3/A", "F-3", "F-3/A", "S-4", "S-4/A", "F-4", "F-4/A",
    "424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8", "POS AM",
}
OWNERSHIP_FORMS = {"3", "3/A", "4", "4/A", "5", "5/A"}

COMMON_PATTERNS = (
    re.compile(r"\bcommon\s+(?:stock|shares?)\b", re.I),
    re.compile(r"\bclass\s+[a-z0-9-]+\s+common\s+(?:stock|shares?)\b", re.I),
    re.compile(r"\bordinary\s+shares?\b", re.I),
    re.compile(r"\bcommon\s+shares?\s+of\s+beneficial\s+interest\b", re.I),
)
NON_COMMON_PATTERNS = (
    re.compile(r"\bpreferred\b", re.I),
    re.compile(r"\bwarrants?\b", re.I),
    re.compile(r"\brights?\b", re.I),
    re.compile(r"\bunits?\b", re.I),
    re.compile(r"\boptions?\b", re.I),
    re.compile(r"\brestricted\s+stock\s+units?\b", re.I),
    re.compile(r"\brsu\b", re.I),
    re.compile(r"\b(?:notes?|debentures?|bonds?|debt)\b", re.I),
    re.compile(r"\bconvertible\b", re.I),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksums(root: Path) -> int:
    manifest = root / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise RuntimeError(f"missing checksum manifest: {manifest}")
    verified = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(None, 1)
        path = root / relative.strip()
        if not path.is_file():
            raise RuntimeError(f"checksum member missing: {relative}")
        if sha256_file(path) != digest:
            raise RuntimeError(f"checksum mismatch: {relative}")
        verified += 1
    return verified


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_gzip_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def cik_from_url(url: str) -> str:
    match = CIK_SUBMISSION_RE.search(url)
    if match:
        return match.group(1)
    match = CIK_ARCHIVE_RE.search(url)
    if not match:
        return ""
    return match.group(1).zfill(10)


def normalize_date8(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else ""


def visible_text(text: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", text))).strip()


def ticker_token_pattern(ticker: str) -> str:
    escaped = re.escape(ticker.upper())
    return rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])"


def explicit_ticker_proofs(raw_text: str, visible: str, ticker: str) -> list[tuple[str, str]]:
    ticker = ticker.upper()
    proofs: list[tuple[str, str]] = []
    for match in ISSUER_TRADING_SYMBOL_RE.finditer(raw_text):
        symbol = SPACE_RE.sub(" ", html.unescape(match.group(1))).strip().upper()
        if symbol == ticker:
            proofs.append(("SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML", symbol))
            break

    token = ticker_token_pattern(ticker)
    label_patterns = (
        re.compile(rf"(?:trading\s+symbol(?:\(s\))?|ticker\s+symbol|issuer\s+trading\s+symbol)\s*[:\-]?\s*.{{0,240}}?{token}", re.I),
        re.compile(rf"{token}.{{0,160}}?(?:trading\s+symbol(?:\(s\))?|ticker\s+symbol)", re.I),
    )
    for pattern in label_patterns:
        match = pattern.search(visible)
        if match:
            proofs.append(("SEC_EXPLICIT_TRADING_SYMBOL_LABEL", match.group(0)[:320]))
            break
    return proofs


def classify_window(window: str) -> tuple[str, str]:
    common = [pattern.search(window) for pattern in COMMON_PATTERNS]
    non_common = [pattern.search(window) for pattern in NON_COMMON_PATTERNS]
    common_hits = [m.group(0) for m in common if m]
    non_common_hits = [m.group(0) for m in non_common if m]
    if common_hits and not non_common_hits:
        return "common", common_hits[0]
    if non_common_hits and not common_hits:
        return "non_common", non_common_hits[0]
    return "unknown", ""


def class_candidate_near_ticker(visible: str, ticker: str) -> tuple[str, str]:
    token = re.compile(ticker_token_pattern(ticker), re.I)
    labels = list(re.finditer(r"(?:trading\s+symbol(?:\(s\))?|ticker\s+symbol|issuer\s+trading\s+symbol)", visible, re.I))
    best: tuple[str, str] = ("unknown", "")
    for label in labels:
        start = max(0, label.start() - 500)
        end = min(len(visible), label.end() + 800)
        window = visible[start:end]
        if not token.search(window):
            continue
        classification, evidence = classify_window(window)
        if classification != "unknown":
            snippet = SPACE_RE.sub(" ", window)[:800]
            best = (classification, f"{evidence} | {snippet}")
            break
    return best


def filing_metadata(raw_text: str, source_url: str) -> tuple[str, str, str, str]:
    form_match = FORM_RE.search(raw_text)
    filed_match = FILED_RE.search(raw_text)
    accession_match = ACCESSION_RE.search(raw_text)
    sic_match = SIC_RE.search(raw_text)
    form = SPACE_RE.sub(" ", form_match.group(1)).strip().upper() if form_match else ""
    filed = normalize_date8(filed_match.group(1)) if filed_match else ""
    accession = accession_match.group(1).strip() if accession_match else ""
    if not accession:
        leaf = source_url.rstrip("/").split("/")[-1]
        if leaf.lower().endswith(".txt"):
            digits = re.sub(r"[^0-9]", "", leaf[:-4])
            accession = digits if digits else ""
    sic = sic_match.group(1).zfill(4) if sic_match else ""
    return form, filed, accession, sic


def within_episode_window(filed: str, first_session: str, last_session: str) -> bool:
    if not filed:
        return True  # unknown filing date is retained as candidate, never admitted.
    try:
        start_year = max(1994, int(first_session[:4]) - 3)
    except (TypeError, ValueError):
        return True
    low = f"{start_year}-01-01"
    high = f"{last_session[:4]}-12-31" if last_session else "9999-12-31"
    return low <= filed <= high


def target_rows(inventory: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    rows = read_gzip_csv(inventory)
    by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        observed = {value for value in str(row.get("observed_ciks") or "").split(";") if value}
        timeline = {value for value in str(row.get("timeline_identity_ciks") or "").split(";") if value}
        hints = {value for value in str(row.get("web_plan_ciks") or "").split(";") if value}
        causal = observed | timeline
        for cik in sorted(causal | hints):
            item = dict(row)
            item["candidate_cik"] = cik
            item["cik_authority"] = "CAUSALLY_ESTABLISHED" if cik in causal else "DISCOVERY_ONLY_HINT"
            by_cik[cik].append(item)
    return rows, by_cik


def mine(shard_root: Path, inventory: Path, output: Path, shard: str) -> dict:
    verified_files = verify_checksums(shard_root)
    runner = json.loads((shard_root / "shard_runner_coverage.json").read_text(encoding="utf-8"))
    web = json.loads((shard_root / "web_coverage.json").read_text(encoding="utf-8"))
    if runner.get("status") != "PASS" or str(runner.get("shard")) != shard:
        raise RuntimeError(f"shard runner authority mismatch for {shard}: {runner}")
    if web.get("status") != "PASS" or not web.get("complete"):
        raise RuntimeError(f"shard {shard} is not transport-complete")

    _inventory_rows, by_cik = target_rows(inventory)
    manifest = read_gzip_csv(shard_root / "web_source_manifest.csv.gz")
    source_candidates = [
        row for row in manifest
        if row.get("status") == "200" and cik_from_url(str(row.get("url") or "")) in by_cik
    ]

    candidate_rows: list[dict[str, object]] = []
    counters = Counter()
    source_hashes_seen: set[str] = set()
    for index, source in enumerate(source_candidates, 1):
        source_url = str(source.get("url") or "")
        cik = cik_from_url(source_url)
        member = str(source.get("artifact_member") or "")
        digest = str(source.get("sha256") or "")
        if not member:
            raise RuntimeError(f"HTTP 200 target source lacks artifact_member: {source_url}")
        path = shard_root / member
        if not path.is_file():
            raise RuntimeError(f"raw source missing: {member}")
        actual = sha256_file(path)
        if digest and actual != digest:
            raise RuntimeError(f"raw source hash mismatch: {member}")
        source_hashes_seen.add(actual)
        counters["target_source_objects_verified"] += 1

        # Submission JSON is useful for inventory/provenance but is not itself
        # treated as exact historical ticker/class authority by this candidate miner.
        if "/submissions/" in source_url.lower():
            counters["target_submission_objects"] += 1
            continue

        data = path.read_bytes()
        raw_text = data.decode("utf-8", errors="replace")
        visible = visible_text(raw_text)
        form, filed, accession, sic = filing_metadata(raw_text, source_url)
        counters["target_filing_objects"] += 1

        for episode in by_cik[cik]:
            ticker = str(episode.get("ticker") or "").upper()
            if not ticker or not within_episode_window(
                filed, str(episode.get("first_session") or ""), str(episode.get("last_session") or "")
            ):
                continue
            proofs = explicit_ticker_proofs(raw_text, visible, ticker)
            if proofs:
                proof_kind, proof_excerpt = proofs[0]
                candidate_rows.append({
                    "shard": shard,
                    "security_id": episode["security_id"],
                    "ticker": ticker,
                    "first_session": episode.get("first_session", ""),
                    "last_session": episode.get("last_session", ""),
                    "resolution_route": episode.get("resolution_route", ""),
                    "candidate_cik": cik,
                    "cik_authority": episode["cik_authority"],
                    "candidate_kind": "IDENTITY_EXACT_TICKER",
                    "candidate_quality": proof_kind,
                    "form": form,
                    "filed": filed,
                    "accession": accession,
                    "classification": "",
                    "sic": "",
                    "evidence_excerpt": proof_excerpt,
                    "source_url": source_url,
                    "source_sha256": actual,
                    "artifact_member": member,
                    "admission_effect": "NONE_CANDIDATE_ONLY",
                })
                counters["identity_candidates"] += 1

                classification, class_evidence = class_candidate_near_ticker(visible, ticker)
                if classification != "unknown":
                    if form in CURRENT_AUTHORITY_FORMS:
                        quality = "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"
                    elif form in EXTENDED_CANDIDATE_FORMS:
                        quality = "EXTENDED_FORM_EXACT_TICKER_CLASS_CANDIDATE"
                    elif form in OWNERSHIP_FORMS:
                        quality = "OWNERSHIP_FORM_SUPPLEMENTARY_CLASS_ONLY"
                    else:
                        quality = "OTHER_FORM_EXACT_TICKER_CLASS_CANDIDATE"
                    candidate_rows.append({
                        "shard": shard,
                        "security_id": episode["security_id"],
                        "ticker": ticker,
                        "first_session": episode.get("first_session", ""),
                        "last_session": episode.get("last_session", ""),
                        "resolution_route": episode.get("resolution_route", ""),
                        "candidate_cik": cik,
                        "cik_authority": episode["cik_authority"],
                        "candidate_kind": "SECURITY_TYPE_EXACT_TICKER_CLASS",
                        "candidate_quality": quality,
                        "form": form,
                        "filed": filed,
                        "accession": accession,
                        "classification": classification,
                        "sic": "",
                        "evidence_excerpt": class_evidence,
                        "source_url": source_url,
                        "source_sha256": actual,
                        "artifact_member": member,
                        "admission_effect": "NONE_CANDIDATE_ONLY",
                    })
                    counters["security_type_candidates"] += 1
                    counters[f"security_type_{quality}"] += 1

            if sic and (episode["cik_authority"] == "CAUSALLY_ESTABLISHED" or proofs):
                quality = (
                    "HEADER_SIC_CAUSAL_CIK"
                    if episode["cik_authority"] == "CAUSALLY_ESTABLISHED"
                    else "HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP"
                )
                candidate_rows.append({
                    "shard": shard,
                    "security_id": episode["security_id"],
                    "ticker": ticker,
                    "first_session": episode.get("first_session", ""),
                    "last_session": episode.get("last_session", ""),
                    "resolution_route": episode.get("resolution_route", ""),
                    "candidate_cik": cik,
                    "cik_authority": episode["cik_authority"],
                    "candidate_kind": "SIC_HEADER",
                    "candidate_quality": quality,
                    "form": form,
                    "filed": filed,
                    "accession": accession,
                    "classification": "",
                    "sic": sic,
                    "evidence_excerpt": f"STANDARD INDUSTRIAL CLASSIFICATION [{sic}]",
                    "source_url": source_url,
                    "source_sha256": actual,
                    "artifact_member": member,
                    "admission_effect": "NONE_CANDIDATE_ONLY",
                })
                counters["sic_candidates"] += 1

        if index % 100 == 0 or index == len(source_candidates):
            print(
                f"[V3 MINE] shard={shard} sources={index}/{len(source_candidates)} "
                f"candidates={len(candidate_rows)}",
                flush=True,
            )

    # Deterministic de-duplication.
    key_fields = (
        "security_id", "candidate_cik", "candidate_kind", "candidate_quality", "form", "filed",
        "accession", "classification", "sic", "source_sha256",
    )
    chosen: dict[tuple[str, ...], dict[str, object]] = {}
    for row in candidate_rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        chosen.setdefault(key, row)
    candidate_rows = [chosen[key] for key in sorted(chosen)]

    fields = [
        "shard", "security_id", "ticker", "first_session", "last_session", "resolution_route",
        "candidate_cik", "cik_authority", "candidate_kind", "candidate_quality", "form", "filed",
        "accession", "classification", "sic", "evidence_excerpt", "source_url", "source_sha256",
        "artifact_member", "admission_effect",
    ]
    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "candidate_evidence.csv.gz", fields, candidate_rows)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "shard": shard,
        "candidate_only": True,
        "admission_effect": "NONE",
        "verified_shard_files": verified_files,
        "target_ciks_present_in_inventory": len(by_cik),
        "target_source_objects_considered": len(source_candidates),
        "unique_target_source_hashes_verified": len(source_hashes_seen),
        "candidate_rows": len(candidate_rows),
        "counts": dict(counters),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def merge(inputs: Path, output: Path, expected_shards: int = 32) -> dict:
    summaries = []
    rows: list[dict[str, str]] = []
    for path in sorted(inputs.rglob("summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if summary.get("status") != "PASS" or not summary.get("candidate_only"):
            raise RuntimeError(f"invalid V3 shard summary: {path}")
        summaries.append(summary)
        candidate_path = path.parent / "candidate_evidence.csv.gz"
        rows.extend(read_gzip_csv(candidate_path))
    shards = {str(summary.get("shard")) for summary in summaries}
    expected = {f"{index:02d}" for index in range(expected_shards)}
    if shards != expected:
        raise RuntimeError(f"V3 candidate shard mismatch: missing={sorted(expected-shards)} extra={sorted(shards-expected)}")

    key_fields = (
        "security_id", "candidate_cik", "candidate_kind", "candidate_quality", "form", "filed",
        "accession", "classification", "sic", "source_sha256",
    )
    chosen: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        prior = chosen.get(key)
        if prior is not None and prior != row:
            # Shard partitioning is by CIK, so a conflicting duplicate is a hard error.
            raise RuntimeError(f"conflicting duplicate V3 candidate: {key}")
        chosen[key] = row
    rows = [chosen[key] for key in sorted(chosen)]

    fields = list(rows[0]) if rows else [
        "shard", "security_id", "ticker", "first_session", "last_session", "resolution_route",
        "candidate_cik", "cik_authority", "candidate_kind", "candidate_quality", "form", "filed",
        "accession", "classification", "sic", "evidence_excerpt", "source_url", "source_sha256",
        "artifact_member", "admission_effect",
    ]
    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "candidate_evidence.csv.gz", fields, rows)

    by_kind = Counter(row.get("candidate_kind", "") for row in rows)
    by_quality = Counter(row.get("candidate_quality", "") for row in rows)
    episodes_by_kind: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        episodes_by_kind[row.get("candidate_kind", "")].add(row.get("security_id", ""))

    strong_identity_bootstrap = {
        row["security_id"]
        for row in rows
        if row.get("candidate_kind") == "IDENTITY_EXACT_TICKER"
        and row.get("cik_authority") == "DISCOVERY_ONLY_HINT"
        and row.get("candidate_quality") in {
            "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML", "SEC_EXPLICIT_TRADING_SYMBOL_LABEL"
        }
    }
    current_form_type = {
        row["security_id"]
        for row in rows
        if row.get("candidate_kind") == "SECURITY_TYPE_EXACT_TICKER_CLASS"
        and row.get("candidate_quality") == "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"
    }
    extended_form_type = {
        row["security_id"]
        for row in rows
        if row.get("candidate_kind") == "SECURITY_TYPE_EXACT_TICKER_CLASS"
        and row.get("candidate_quality") == "EXTENDED_FORM_EXACT_TICKER_CLASS_CANDIDATE"
    }
    sic_episode_candidates = episodes_by_kind.get("SIC_HEADER", set())

    summary = {
        "schema": MERGE_SCHEMA,
        "status": "PASS",
        "candidate_only": True,
        "admission_effect": "NONE",
        "merged_shards": len(shards),
        "candidate_rows": len(rows),
        "candidate_counts_by_kind": dict(by_kind),
        "candidate_counts_by_quality": dict(by_quality),
        "episodes_with_identity_candidates": len(episodes_by_kind.get("IDENTITY_EXACT_TICKER", set())),
        "episodes_with_security_type_candidates": len(episodes_by_kind.get("SECURITY_TYPE_EXACT_TICKER_CLASS", set())),
        "episodes_with_sic_candidates": len(sic_episode_candidates),
        "discovery_hint_episodes_with_strong_identity_bootstrap_candidate": len(strong_identity_bootstrap),
        "episodes_with_current_form_type_candidate": len(current_form_type),
        "episodes_with_extended_form_type_candidate": len(extended_form_type),
        "next_gate": "authority review and causal episode allocation; no candidate is admitted automatically",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("mine")
    p.add_argument("--shard-root", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--shard", required=True)
    p = sub.add_parser("merge")
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expected-shards", type=int, default=32)
    args = parser.parse_args()
    if args.cmd == "mine":
        result = mine(args.shard_root, args.inventory, args.output, args.shard)
    else:
        result = merge(args.inputs, args.output, args.expected_shards)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
