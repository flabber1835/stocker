#!/usr/bin/env python3
"""Bounded V4 SEC authority expansion for unresolved PIT metadata.

EFTS is discovery-only. Candidate authority requires an exact archived SEC filing,
an exact historical ticker proof, and filing_date < the first unresolved canonical
observation. This module never mutates the canonical PIT package.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from backtester.historical_metadata_reconstruction_v2 import (
    ReconstructionError,
    SecHttpTransport,
    filing_url,
    read_gzip_csv,
    sha256_bytes,
    sha256_file,
    validate_cik,
    write_checksums,
    write_gzip_csv,
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
    "security_id", "ticker", "bucket", "authority_before", "candidate_cik",
    "accession", "form", "filed", "identity_proof_kind",
    "identity_proof_excerpt", "classification", "classification_excerpt", "sic",
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
DISPLAY_TICKER = r"(?:^|[\s(,;/]){ticker}(?:[\s),;/]|$)"


def _int(row: Mapping[str, str], key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def authority_before(row: Mapping[str, str]) -> str:
    dates = []
    if _int(row, "type_unresolved") and row.get("type_first"):
        dates.append(str(row["type_first"])[:10])
    if _int(row, "sector_unresolved") and row.get("sector_first"):
        dates.append(str(row["sector_first"])[:10])
    if not dates:
        raise ReconstructionError(
            f"unresolved episode lacks causal boundary: {row.get('security_id')}"
        )
    return min(dates)


def build_plan(
    inventory: Path, output: Path, limit: int = 0, include_tickers: Sequence[str] = ()
) -> dict:
    source_rows = read_gzip_csv(inventory)
    rows = []
    for source in source_rows:
        boundary = authority_before(source)
        if boundary <= "2001-01-01":
            continue
        impact = (
            _int(source, "type_unresolved")
            + _int(source, "sector_unresolved")
            + _int(source, "issuer_unresolved")
        )
        rows.append({
            "security_id": str(source.get("security_id") or ""),
            "ticker": str(source.get("ticker") or "").upper(),
            "first_session": str(source.get("first_session") or "")[:10],
            "last_session": str(source.get("last_session") or "")[:10],
            "bucket": str(source.get("bucket") or ""),
            "type_unresolved": _int(source, "type_unresolved"),
            "sector_unresolved": _int(source, "sector_unresolved"),
            "issuer_unresolved": _int(source, "issuer_unresolved"),
            "authority_before": boundary,
            "search_start": "2001-01-01",
            "search_end": (dt.date.fromisoformat(boundary) - dt.timedelta(days=1)).isoformat(),
            "impact": impact,
        })
    rows.sort(key=lambda r: (-int(r["impact"]), str(r["ticker"]), str(r["security_id"])))
    requested = {str(t).strip().upper() for t in include_tickers if str(t).strip()}
    forced = [r for r in rows if r["ticker"] in requested]
    if limit > 0:
        forced_ids = {str(r["security_id"]) for r in forced}
        selected = list(forced)
        selected.extend(
            r for r in rows
            if str(r["security_id"]) not in forced_ids
        )
        rows = selected[:max(limit, len(forced))]
    rows.sort(key=lambda r: (str(r["ticker"]), str(r["security_id"])))

    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.csv.gz"
    write_gzip_csv(plan_path, PLAN_FIELDS, rows)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "role": "bounded discovery plan; no admission authority",
        "inventory_rows": len(source_rows),
        "planned_rows": len(rows),
        "unique_tickers": len({str(r["ticker"]) for r in rows}),
        "search_floor": "2001-01-01",
        "strict_prior_rule": "filing_date < earliest unresolved canonical observation",
        "included_tickers_requested": sorted(requested),
        "included_tickers_present": sorted(requested & {str(r["ticker"]) for r in rows}),
        "plan_sha256": sha256_file(plan_path),
    }
    (output / "plan_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksums(output)
    return summary


def build_discovery_url(row: Mapping[str, str], offset: int = 0) -> str:
    return EFTS + "?" + urllib.parse.urlencode({
        "q": f'"{str(row["ticker"]).upper()}"',
        "startdt": str(row["search_start"]),
        "enddt": str(row["search_end"]),
        "from": str(offset),
    })


def parse_efts(payload: bytes) -> tuple[int, list[dict[str, object]]]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReconstructionError(f"EFTS response is not JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("timed_out") is True:
        raise ReconstructionError("EFTS response is partial or malformed")
    block = value.get("hits")
    if not isinstance(block, dict) or not isinstance(block.get("hits"), list):
        raise ReconstructionError("EFTS response lacks hits.hits")
    raw_total = block.get("total", 0)
    total = int(raw_total.get("value") or 0) if isinstance(raw_total, dict) else int(raw_total or 0)
    rows = []
    for hit in block["hits"]:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        ciks = [validate_cik(c) for c in (source.get("ciks") or [])]
        ciks = [c for c in ciks if c]
        accession = str(source.get("adsh") or "").strip()
        filed = str(source.get("file_date") or "").strip()[:10]
        if not ciks or not accession or not filed:
            continue
        rows.append({
            "accession": accession,
            "filed": filed,
            "form": str(source.get("form") or "").strip().upper(),
            "ciks": ciks,
            "display_names": [str(v) for v in (source.get("display_names") or [])],
            "hit_id": str(hit.get("_id") or ""),
        })
    return total, rows


def display_name_matches_ticker(display_names: Sequence[str], ticker: str) -> bool:
    pattern = re.compile(DISPLAY_TICKER.format(ticker=re.escape(ticker.upper())), re.I)
    return any(pattern.search(name.upper()) for name in display_names)


def historical_ticker_proofs(raw_text: str, visible: str, ticker: str) -> list[tuple[str, str]]:
    proofs = explicit_ticker_proofs(raw_text, visible, ticker)
    if proofs:
        return proofs
    token = re.escape(ticker.upper())
    pattern = re.compile(
        rf"\b(?:NYSE|NASDAQ|AMEX|NYSE\s+AMERICAN|NYSE\s+MKT|OTCBB|OTCQB|OTCQX|OTC|TSX|LSE)"
        rf"\s*[:\-]\s*{token}(?![A-Z0-9])",
        re.I,
    )
    match = pattern.search(visible)
    return [("SEC_EXCHANGE_QUALIFIED_TICKER", match.group(0))] if match else []


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
    row: Mapping[str, str], cik: str, accession: str, data: bytes,
    source_url: str, discovery_url: str, discovery_sha256: str, source_member: str,
) -> dict[str, object] | None:
    raw = data.decode("utf-8", errors="replace")
    visible = visible_text(raw)
    ticker = str(row["ticker"]).upper()
    proofs = historical_ticker_proofs(raw, visible, ticker)
    if not proofs:
        return None
    form, filed, parsed_accession, sic = filing_metadata(raw, source_url)
    filed = filed or str(row.get("_hit_filed") or "")
    form = (form or str(row.get("_hit_form") or "")).upper()
    if not filed or filed >= str(row["authority_before"]):
        return None
    classification, class_excerpt = class_candidate_near_ticker(visible, ticker)
    if form in CURRENT_AUTHORITY_FORMS:
        form_authority = "CURRENT_AUTHORITY_FORM"
    elif form in EXTENDED_CANDIDATE_FORMS:
        form_authority = "EXTENDED_CANDIDATE_FORM"
    elif form in OWNERSHIP_FORMS:
        form_authority = "OWNERSHIP_CANDIDATE_FORM"
    else:
        form_authority = "UNREVIEWED_FORM"
    proof_kind, proof_excerpt = proofs[0]
    return {
        "security_id": row["security_id"],
        "ticker": ticker,
        "bucket": row.get("bucket", ""),
        "authority_before": row["authority_before"],
        "candidate_cik": cik,
        "accession": parsed_accession or accession,
        "form": form,
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
    plan_path: Path, output: Path, min_interval: float = 1.0,
    max_pages: int = 3, max_filings_per_episode: int = 8,
) -> dict:
    plan = read_gzip_csv(plan_path)
    output.mkdir(parents=True, exist_ok=True)
    client = SecHttpTransport(output / ".http-cache", min_interval=min_interval)
    manifest, evidence, results = [], [], []
    counters = Counter()

    for index, row in enumerate(plan, 1):
        ticker = str(row["ticker"]).upper()
        hits, discovery = [], []
        total = 0
        for page in range(max(1, max_pages)):
            url = build_discovery_url(row, page * 100)
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
            discovery.append((url, digest))
            page_total, page_hits = parse_efts(data)
            total = max(total, page_total)
            hits.extend(page_hits)
            counters["discovery_requests"] += 1
            if not page_hits or len(hits) >= total:
                break

        exact = [
            h for h in hits
            if str(h["filed"]) < str(row["authority_before"])
            and display_name_matches_ticker(h.get("display_names", []), ticker)
        ]
        candidates: dict[tuple[str, str], dict[str, object]] = {}
        for hit in exact:
            for cik in hit["ciks"]:
                candidates.setdefault((str(cik), str(hit["accession"])), hit)
        selected = sorted(
            candidates.items(),
            key=lambda item: (str(item[1]["filed"]), item[0][1]),
            reverse=True,
        )[:max(0, max_filings_per_episode)]

        episode_evidence = []
        for (cik, accession), hit in selected:
            url = filing_url(cik, accession)
            data, http = client.get(url)
            counters["filing_requests"] += 1
            if data is None:
                manifest.append({
                    "security_id": row["security_id"], "ticker": ticker,
                    "role": "ARCHIVED_FILING_AUTHORITY_CANDIDATE", "url": url,
                    "status": http.status, "sha256": "", "bytes": 0,
                    "retrieved_at": http.retrieved_at, "artifact_member": "",
                })
                continue
            member, digest = _save_source(output, "filings", data)
            manifest.append({
                "security_id": row["security_id"], "ticker": ticker,
                "role": "ARCHIVED_FILING_AUTHORITY_CANDIDATE", "url": url,
                "status": http.status, "sha256": digest, "bytes": len(data),
                "retrieved_at": http.retrieved_at, "artifact_member": member,
            })
            enriched = dict(row)
            enriched["_hit_filed"], enriched["_hit_form"] = hit["filed"], hit["form"]
            candidate = analyze_filing(
                enriched, cik, accession, data, url, discovery[0][0], discovery[0][1], member
            )
            if candidate:
                episode_evidence.append(candidate)

        ciks = sorted({str(e["candidate_cik"]) for e in episode_evidence})
        if len(ciks) > 1:
            status, reason = "AMBIGUOUS", "multiple_ciks_have_strict_prior_exact_ticker_proof"
        elif episode_evidence:
            status, reason = "CANDIDATE_FOUND", "strict_prior_exact_archived_filing_evidence"
        elif exact:
            status, reason = (
                "NO_ARCHIVED_PROOF",
                "display_name_discovery_hits_did_not_prove_exact_ticker_in_filing",
            )
        else:
            status, reason = (
                "NO_DISCOVERY_MATCH",
                "no_strict_prior_efts_hit_with_exact_display_ticker",
            )
        evidence.extend(episode_evidence)
        results.append({
            "security_id": row["security_id"], "ticker": ticker,
            "authority_before": row["authority_before"], "discovery_hits": len(hits),
            "display_name_exact_hits": len(exact), "candidate_accessions": len(candidates),
            "filings_fetched": len(selected),
            "admissible_identity_ciks": ";".join(ciks) if len(ciks) == 1 else "",
            "candidate_rows": len(episode_evidence), "status": status, "reason": reason,
        })
        counters[f"episode_{status.lower()}"] += 1
        print(
            f"[V4] episode={index}/{len(plan)} ticker={ticker} status={status} "
            f"hits={len(hits)} exact={len(exact)} candidates={len(episode_evidence)}",
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
    write_gzip_csv(output / "candidate_evidence.csv.gz", EVIDENCE_FIELDS, evidence)
    write_gzip_csv(output / "episode_results.csv.gz", RESULT_FIELDS, results)
    write_gzip_csv(output / "source_manifest.csv.gz", MANIFEST_FIELDS, manifest)
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
    write_checksums(output, exclude={".http-cache"})
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--include-ticker", action="append", default=[])
    h = sub.add_parser("harvest")
    h.add_argument("--plan", type=Path, required=True)
    h.add_argument("--output", type=Path, required=True)
    h.add_argument("--min-interval", type=float, default=1.0)
    h.add_argument("--max-pages", type=int, default=3)
    h.add_argument("--max-filings-per-episode", type=int, default=8)
    args = parser.parse_args(argv)
    result = (
        build_plan(args.inventory, args.output, args.limit, args.include_ticker)
        if args.command == "plan"
        else harvest(
            args.plan, args.output, args.min_interval, args.max_pages,
            args.max_filings_per_episode,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
