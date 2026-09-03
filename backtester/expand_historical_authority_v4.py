#!/usr/bin/env python3
"""V4 bounded historical SEC authority expansion for unresolved PIT metadata.

The SEC full-text search response is discovery-only. Authority can come only from
an exact archived filing whose filing date is strictly before the unresolved
canonical observation and whose content proves the exact ticker. This module
never mutates the canonical PIT package and never converts unknown metadata into
an eligibility decision.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backtester.historical_metadata_reconstruction_v2 import (
    ReconstructionError,
    SecHttpTransport,
    filing_url,
    sha256_bytes,
    sha256_file,
    validate_cik,
)
from backtester.mine_historical_metadata_candidates_v3 import (
    CURRENT_AUTHORITY_FORMS,
    EXTENDED_CANDIDATE_FORMS,
    OWNERSHIP_FORMS,
    class_candidate_near_ticker,
    explicit_ticker_proofs,
    filing_metadata,
    visible_text,
)

SCHEMA = "backtester.historical-metadata-authority-expansion-v4/1"
EFTS = "https://efts.sec.gov/LATEST/search-index"
PLAN_FIELDS = [
    "security_id", "ticker", "first_session", "last_session", "bucket",
    "type_unresolved", "sector_unresolved", "issuer_unresolved",
    "authority_before", "search_start", "search_end", "impact",
]
EVIDENCE_FIELDS = [
    "security_id", "ticker", "bucket", "authority_before",
    "candidate_cik", "accession", "form", "filed",
    "identity_proof_kind", "identity_proof_excerpt",
    "classification", "classification_excerpt", "sic",
    "form_authority", "source_url", "source_sha256", "source_member",
    "discovery_url", "discovery_sha256", "admission_effect",
]
RESULT_FIELDS = [
    "security_id", "ticker", "authority_before", "discovery_hits",
    "display_name_exact_hits", "candidate_accessions", "filings_fetched",
    "admissible_identity_ciks", "candidate_rows", "status", "reason",
]
MANIFEST_FIELDS = [
    "security_id", "ticker", "role", "url", "status", "sha256", "bytes",
    "retrieved_at", "artifact_member",
]

DISPLAY_TICKER_RE_TEMPLATE = r"(?:^|[\s(]){ticker}(?:[\s)]|$)"


def _read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_gzip_csv(
    path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(
                    text, fieldnames=list(fields), extrasaction="ignore", lineterminator="\n"
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def _write_checksums(root: Path) -> None:
    members = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        if ".http-cache" in path.parts:
            continue
        members.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(members) + "\n", encoding="utf-8")


def _day_before(value: str) -> str:
    return (dt.date.fromisoformat(value) - dt.timedelta(days=1)).isoformat()


def _int(row: Mapping[str, str], key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def authority_before(row: Mapping[str, str]) -> str:
    dates: list[str] = []
    if _int(row, "type_unresolved") > 0 and row.get("type_first"):
        dates.append(str(row["type_first"])[:10])
    if _int(row, "sector_unresolved") > 0 and row.get("sector_first"):
        dates.append(str(row["sector_first"])[:10])
    if not dates:
        raise ReconstructionError(
            f"unresolved episode lacks a type/sector causal boundary: {row.get('security_id')}"
        )
    return min(dates)


def build_plan(
    inventory: Path,
    output: Path,
    limit: int = 0,
    include_tickers: Sequence[str] = (),
) -> dict:
    rows = _read_gzip_csv(inventory)
    plan: list[dict[str, object]] = []
    for row in rows:
        boundary = authority_before(row)
        if boundary <= "2001-01-01":
            continue
        impact = (
            _int(row, "type_unresolved")
            + _int(row, "sector_unresolved")
            + _int(row, "issuer_unresolved")
        )
        plan.append({
            "security_id": str(row.get("security_id") or ""),
            "ticker": str(row.get("ticker") or "").upper(),
            "first_session": str(row.get("first_session") or "")[:10],
            "last_session": str(row.get("last_session") or "")[:10],
            "bucket": str(row.get("bucket") or ""),
            "type_unresolved": _int(row, "type_unresolved"),
            "sector_unresolved": _int(row, "sector_unresolved"),
            "issuer_unresolved": _int(row, "issuer_unresolved"),
            "authority_before": boundary,
            "search_start": "2001-01-01",
            "search_end": _day_before(boundary),
            "impact": impact,
        })
    plan.sort(key=lambda r: (-int(r["impact"]), str(r["ticker"]), str(r["security_id"])))

    requested = {str(t).strip().upper() for t in include_tickers if str(t).strip()}
    forced = [r for r in plan if r["ticker"] in requested]
    if limit > 0:
        forced_ids = {str(r["security_id"]) for r in forced}
        selected = list(forced)
        for row in plan:
            if str(row["security_id"]) in forced_ids:
                continue
            if len(selected) >= limit:
                break
            selected.append(row)
        plan = selected[:max(limit, len(forced))]
    plan.sort(key=lambda r: (str(r["ticker"]), str(r["security_id"])))

    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.csv.gz"
    _write_gzip_csv(plan_path, PLAN_FIELDS, plan)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "role": "bounded discovery plan; no admission authority",
        "inventory_rows": len(rows),
        "planned_rows": len(plan),
        "unique_tickers": len({str(r["ticker"]) for r in plan}),
        "search_floor": "2001-01-01",
        "strict_prior_rule": "filing_date < earliest unresolved canonical observation",
        "included_tickers_requested": sorted(requested),
        "included_tickers_present": sorted(requested & {str(r["ticker"]) for r in plan}),
        "plan_sha256": sha256_file(plan_path),
    }
    (output / "plan_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_checksums(output)
    return summary


def build_discovery_url(row: Mapping[str, str], offset: int = 0) -> str:
    params = {
        "q": f'"{str(row["ticker"]).upper()}"',
        "startdt": str(row["search_start"]),
        "enddt": str(row["search_end"]),
        "from": str(offset),
    }
    return EFTS + "?" + urllib.parse.urlencode(params)


def parse_efts(payload: bytes) -> tuple[int, list[dict[str, object]]]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReconstructionError(f"EFTS response is not JSON: {exc}") from exc
    if not isinstance(parsed, dict) or parsed.get("timed_out") is True:
        raise ReconstructionError("EFTS response is partial or malformed")
    hits_block = parsed.get("hits")
    if not isinstance(hits_block, dict) or not isinstance(hits_block.get("hits"), list):
        raise ReconstructionError("EFTS response lacks hits.hits")
    total_raw = hits_block.get("total", 0)
    if isinstance(total_raw, dict):
        total = int(total_raw.get("value") or 0)
    else:
        total = int(total_raw or 0)
    result: list[dict[str, object]] = []
    for hit in hits_block["hits"]:
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source")
        if not isinstance(source, dict):
            continue
        accession = str(source.get("adsh") or "").strip()
        filed = str(source.get("file_date") or "").strip()[:10]
        form = str(source.get("form") or "").strip().upper()
        ciks = [validate_cik(c) for c in (source.get("ciks") or [])]
        ciks = [c for c in ciks if c]
        display_names = [str(v) for v in (source.get("display_names") or [])]
        if not accession or not filed or not ciks:
            continue
        result.append({
            "accession": accession,
            "filed": filed,
            "form": form,
            "ciks": ciks,
            "display_names": display_names,
            "hit_id": str(hit.get("_id") or ""),
        })
    return total, result


def display_name_matches_ticker(display_names: Sequence[str], ticker: str) -> bool:
    escaped = re.escape(ticker.upper())
    pattern = re.compile(DISPLAY_TICKER_RE_TEMPLATE.format(ticker=escaped), re.I)
    return any(pattern.search(name.upper()) for name in display_names)


def _save_source(root: Path, category: str, data: bytes) -> tuple[str, str]:
    digest = sha256_bytes(data)
    member = f"sources/{category}/{digest}.bin"
    path = root / member
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != data:
        raise ReconstructionError(f"content-address collision: {path}")
    if not path.exists():
        path.write_bytes(data)
    return member, digest


def analyze_filing(
    row: Mapping[str, str],
    cik: str,
    accession: str,
    data: bytes,
    source_url: str,
    discovery_url: str,
    discovery_sha256: str,
    source_member: str,
) -> dict[str, object] | None:
    text = data.decode("utf-8", errors="replace")
    visible = visible_text(text)
    ticker = str(row["ticker"]).upper()
    proofs = explicit_ticker_proofs(text, visible, ticker)
    if not proofs:
        return None

    form, filed, parsed_accession, sic = filing_metadata(text, source_url)
    filed = filed or str(row.get("_hit_filed") or "")
    form = form or str(row.get("_hit_form") or "")
    accession = parsed_accession or accession
    if not filed or filed >= str(row["authority_before"]):
        return None

    classification, class_excerpt = class_candidate_near_ticker(visible, ticker)
    proof_kind, proof_excerpt = proofs[0]
    form_upper = form.upper()
    if form_upper in CURRENT_AUTHORITY_FORMS:
        form_authority = "CURRENT_AUTHORITY_FORM"
    elif form_upper in EXTENDED_CANDIDATE_FORMS:
        form_authority = "EXTENDED_CANDIDATE_FORM"
    elif form_upper in OWNERSHIP_FORMS:
        form_authority = "OWNERSHIP_CANDIDATE_FORM"
    else:
        form_authority = "UNREVIEWED_FORM"

    return {
        "security_id": row["security_id"],
        "ticker": ticker,
        "bucket": row.get("bucket", ""),
        "authority_before": row["authority_before"],
        "candidate_cik": cik,
        "accession": accession,
        "form": form_upper,
        "filed": filed,
        "identity_proof_kind": proof_kind,
        "identity_proof_excerpt": str(proof_excerpt)[:500],
        "classification": classification,
        "classification_excerpt": str(class_excerpt)[:800],
        "sic": sic,
        "form_authority": form_authority,
        "source_url": source_url,
        "source_sha256": sha256_bytes(data),
        "source_member": source_member,
        "discovery_url": discovery_url,
        "discovery_sha256": discovery_sha256,
        "admission_effect": "NONE_CANDIDATE_ONLY",
    }


def harvest(
    plan_path: Path,
    output: Path,
    min_interval: float = 1.0,
    max_pages: int = 3,
    max_filings_per_episode: int = 8,
) -> dict:
    plan = _read_gzip_csv(plan_path)
    output.mkdir(parents=True, exist_ok=True)
    client = SecHttpTransport(output / ".http-cache", min_interval=min_interval)
    manifest: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    counters = Counter()

    for index, row in enumerate(plan, 1):
        ticker = str(row["ticker"]).upper()
        all_hits: list[dict[str, object]] = []
        discovery_records: list[tuple[str, str]] = []
        total = 0

        for page in range(max(1, max_pages)):
            offset = page * 100
            url = build_discovery_url(row, offset=offset)
            data, http = client.get(url)
            if data is None:
                raise ReconstructionError(f"EFTS discovery unexpectedly absent: {url}")
            member, digest = _save_source(output, "efts", data)
            manifest.append({
                "security_id": row["security_id"], "ticker": ticker,
                "role": "DISCOVERY_ONLY_EFTS", "url": url, "status": http.status,
                "sha256": digest, "bytes": len(data), "retrieved_at": http.retrieved_at,
                "artifact_member": member,
            })
            discovery_records.append((url, digest))
            page_total, page_hits = parse_efts(data)
            total = max(total, page_total)
            all_hits.extend(page_hits)
            counters["discovery_requests"] += 1
            if not page_hits or len(all_hits) >= total or (page + 1) >= max_pages:
                break

        exact_hits = [
            hit for hit in all_hits
            if display_name_matches_ticker(hit.get("display_names", []), ticker)
            and str(hit.get("filed") or "") < str(row["authority_before"])
        ]
        by_accession: dict[tuple[str, str], dict[str, object]] = {}
        for hit in exact_hits:
            for cik in hit["ciks"]:
                by_accession.setdefault((str(cik), str(hit["accession"])), hit)

        selected = sorted(
            by_accession.items(),
            key=lambda item: (str(item[1]["filed"]), item[0][1]),
            reverse=True,
        )[:max(0, max_filings_per_episode)]

        episode_evidence: list[dict[str, object]] = []
        for (cik, accession), hit in selected:
            source_url = filing_url(cik, accession)
            data, http = client.get(source_url)
            counters["filing_requests"] += 1
            if data is None:
                manifest.append({
                    "security_id": row["security_id"], "ticker": ticker,
                    "role": "ARCHIVED_FILING_AUTHORITY_CANDIDATE", "url": source_url,
                    "status": http.status, "sha256": "", "bytes": 0,
                    "retrieved_at": http.retrieved_at, "artifact_member": "",
                })
                continue
            member, digest = _save_source(output, "filings", data)
            manifest.append({
                "security_id": row["security_id"], "ticker": ticker,
                "role": "ARCHIVED_FILING_AUTHORITY_CANDIDATE", "url": source_url,
                "status": http.status, "sha256": digest, "bytes": len(data),
                "retrieved_at": http.retrieved_at, "artifact_member": member,
            })
            enriched = dict(row)
            enriched["_hit_filed"] = hit["filed"]
            enriched["_hit_form"] = hit["form"]
            discovery_url, discovery_digest = discovery_records[0]
            candidate = analyze_filing(
                enriched, cik, accession, data, source_url,
                discovery_url, discovery_digest, member,
            )
            if candidate is not None:
                episode_evidence.append(candidate)

        identity_ciks = sorted({str(e["candidate_cik"]) for e in episode_evidence})
        if len(identity_ciks) > 1:
            status = "AMBIGUOUS"
            reason = "multiple_ciks_have_strict_prior_exact_ticker_proof"
        elif episode_evidence:
            status = "CANDIDATE_FOUND"
            reason = "strict_prior_exact_archived_filing_evidence"
        elif exact_hits:
            status = "NO_ARCHIVED_PROOF"
            reason = "display_name_discovery_hits_did_not_prove_exact_ticker_in_filing"
        else:
            status = "NO_DISCOVERY_MATCH"
            reason = "no_strict_prior_efts_hit_with_exact_display_ticker"

        evidence.extend(episode_evidence)
        results.append({
            "security_id": row["security_id"],
            "ticker": ticker,
            "authority_before": row["authority_before"],
            "discovery_hits": len(all_hits),
            "display_name_exact_hits": len(exact_hits),
            "candidate_accessions": len(by_accession),
            "filings_fetched": len(selected),
            "admissible_identity_ciks": ";".join(identity_ciks) if len(identity_ciks) == 1 else "",
            "candidate_rows": len(episode_evidence),
            "status": status,
            "reason": reason,
        })
        counters[f"episode_{status.lower()}"] += 1
        print(
            f"[V4] episode={index}/{len(plan)} ticker={ticker} status={status} "
            f"hits={len(all_hits)} exact={len(exact_hits)} candidates={len(episode_evidence)}",
            flush=True,
        )

    evidence.sort(key=lambda r: (
        str(r["ticker"]), str(r["security_id"]), str(r["filed"]),
        str(r["candidate_cik"]), str(r["accession"]),
    ))
    results.sort(key=lambda r: (str(r["ticker"]), str(r["security_id"])))
    manifest.sort(key=lambda r: (
        str(r["ticker"]), str(r["security_id"]), str(r["role"]), str(r["url"])
    ))

    _write_gzip_csv(output / "candidate_evidence.csv.gz", EVIDENCE_FIELDS, evidence)
    _write_gzip_csv(output / "episode_results.csv.gz", RESULT_FIELDS, results)
    _write_gzip_csv(output / "source_manifest.csv.gz", MANIFEST_FIELDS, manifest)

    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "admission_status": "REVIEW_REQUIRED",
        "candidate_only": True,
        "canonical_price_dataset_rewritten": False,
        "unknown_never_means_ineligible": True,
        "discovery_is_authority": False,
        "strict_prior_rule": "filing_date < earliest unresolved canonical observation",
        "episodes": len(plan),
        "candidate_found": sum(r["status"] == "CANDIDATE_FOUND" for r in results),
        "ambiguous": sum(r["status"] == "AMBIGUOUS" for r in results),
        "no_discovery_match": sum(r["status"] == "NO_DISCOVERY_MATCH" for r in results),
        "no_archived_proof": sum(r["status"] == "NO_ARCHIVED_PROOF" for r in results),
        "candidate_evidence_rows": len(evidence),
        "unique_candidate_ciks": len({str(r["candidate_cik"]) for r in evidence}),
        "transport": dict(client.counters),
        "next_gate": "explicit V4 authority allocation followed by full canonical observation audit",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_checksums(output)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--inventory", type=Path, required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    plan_parser.add_argument("--limit", type=int, default=0)
    plan_parser.add_argument("--include-ticker", action="append", default=[])

    harvest_parser = sub.add_parser("harvest")
    harvest_parser.add_argument("--plan", type=Path, required=True)
    harvest_parser.add_argument("--output", type=Path, required=True)
    harvest_parser.add_argument("--min-interval", type=float, default=1.0)
    harvest_parser.add_argument("--max-pages", type=int, default=3)
    harvest_parser.add_argument("--max-filings-per-episode", type=int, default=8)

    args = parser.parse_args(argv)
    if args.command == "plan":
        result = build_plan(args.inventory, args.output, args.limit, args.include_ticker)
    else:
        result = harvest(
            args.plan, args.output, args.min_interval,
            args.max_pages, args.max_filings_per_episode,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
