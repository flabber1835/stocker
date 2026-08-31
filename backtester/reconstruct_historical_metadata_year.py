#!/usr/bin/env python3
"""Harvest causally dated SEC metadata evidence for one calendar year.

Each run consumes a precomputed candidate list from the frozen canonical PIT dataset.
Current SEC ticker metadata is discovery-only. Historical identity is admitted only
when a historically filed SEC primary document independently verifies the ticker.
Economic use remains subject to ``filed < decision_session``.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import http.client
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtester.reconstruct_historical_metadata_2006 as base


class ReconstructionError(RuntimeError):
    pass


class SecClient:
    def __init__(self, cache: Path, delay: float, year: int):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.year = year
        self.requests = 0
        self.cache_hits = 0
        self.failures: list[dict[str, str]] = []

    def _path(self, url: str) -> Path:
        return self.cache / hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, url: str) -> bytes:
        path = self._path(url)
        if path.exists():
            self.cache_hits += 1
            return path.read_bytes()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": base.USER_AGENT,
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        last: Exception | None = None
        retryable = (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
        )
        for attempt in range(8):
            tmp = Path(str(path) + f".tmp-{os.getpid()}")
            try:
                time.sleep(self.delay)
                with urllib.request.urlopen(req, timeout=60) as response:
                    data = response.read()
                tmp.write_bytes(data)
                tmp.replace(path)
                self.requests += 1
                return data
            except retryable as exc:
                last = exc
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
                print(
                    f"[RETRY] year={self.year} attempt={attempt + 1}/8 url={url} error={type(exc).__name__}",
                    flush=True,
                )
                time.sleep(min(20.0, 0.75 * (2 ** attempt)))
        self.failures.append({"url": url, "error": repr(last)})
        raise ReconstructionError(f"SEC fetch failed after retries: {url}: {last}")

    def json(self, url: str) -> dict:
        return json.loads(self.get(url).decode("utf-8"))


def load_candidates(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    result: list[dict] = []
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            row["observations"] = int(row.get("observations") or 0)
            row["unknown_type_observations"] = int(row.get("unknown_type_observations") or 0)
            row["missing_sector_observations"] = int(row.get("missing_sector_observations") or 0)
            row["observed_ciks_set"] = {
                base.norm_cik(x) for x in (row.get("observed_ciks") or "").split(";") if base.norm_cik(x)
            }
            result.append(row)
    return result


def filing_rows(payload: dict) -> Iterator[dict[str, str]]:
    recent = payload.get("filings", {}).get("recent") if isinstance(payload.get("filings"), dict) else None
    table = recent if isinstance(recent, dict) else payload
    if not isinstance(table, dict) or "accessionNumber" not in table:
        return
    keys = ["accessionNumber", "filingDate", "form", "primaryDocument"]
    columns = {k: table.get(k, []) for k in keys}
    for i in range(len(columns["accessionNumber"])):
        yield {k: str(columns[k][i] if i < len(columns[k]) else "") for k in keys}


def load_submission_history(client: SecClient, cik: str, start: str, end: str) -> list[dict[str, str]]:
    root = client.json(f"{base.SEC_SUBMISSIONS}/CIK{cik}.json")
    rows = list(filing_rows(root))
    files = root.get("filings", {}).get("files", []) if isinstance(root.get("filings"), dict) else []
    for meta in files:
        if not isinstance(meta, dict):
            continue
        filing_from = str(meta.get("filingFrom") or "")
        filing_to = str(meta.get("filingTo") or "")
        if filing_from and filing_from > end:
            continue
        if filing_to and filing_to < start:
            continue
        name = str(meta.get("name") or "")
        if not name:
            continue
        try:
            rows.extend(filing_rows(client.json(f"{base.SEC_SUBMISSIONS}/{name}")))
        except (ReconstructionError, json.JSONDecodeError):
            continue
    unique = {(r["accessionNumber"], r["filingDate"], r["form"], r["primaryDocument"]): r for r in rows}
    return sorted(unique.values(), key=lambda r: (r["filingDate"], r["accessionNumber"]))


def choose_filings(rows: Iterable[dict[str, str]], year: int, start: str, end: str) -> list[dict[str, str]]:
    forms = base.OWNERSHIP_FORMS | base.PERIODIC_FORMS
    eligible = [r for r in rows if start <= r["filingDate"] <= end and r["form"].upper() in forms]
    ownership = [r for r in eligible if r["form"].upper() in base.OWNERSHIP_FORMS]
    periodic = [r for r in eligible if r["form"].upper() in base.PERIODIC_FORMS]
    year_start = f"{year}-01-01"
    prior_year_start = f"{year - 1}-01-01"
    selected: dict[str, dict[str, str]] = {}

    pre_own = [r for r in ownership if r["filingDate"] < year_start]
    in_own = [r for r in ownership if r["filingDate"] >= year_start]
    if pre_own:
        selected[pre_own[-1]["accessionNumber"]] = pre_own[-1]
    if in_own:
        selected[in_own[0]["accessionNumber"]] = in_own[0]
        selected[in_own[-1]["accessionNumber"]] = in_own[-1]

    pre_periodic = [r for r in periodic if r["filingDate"] < year_start]
    if pre_periodic:
        selected[pre_periodic[-1]["accessionNumber"]] = pre_periodic[-1]
    for r in periodic:
        if r["filingDate"] >= prior_year_start:
            selected[r["accessionNumber"]] = r
    return sorted(selected.values(), key=lambda r: (r["filingDate"], r["accessionNumber"]))


def write_csv_gz(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            import io
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)


def write_gzip_bytes(path: Path, data: bytes) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(data)


def dedup(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    chosen: dict[tuple[str, ...], dict] = {}
    for row in rows:
        key = tuple(str(row.get(k, "")) for k in keys)
        chosen.setdefault(key, row)
    return [chosen[k] for k in sorted(chosen)]


def progress(year: int, done: int, total: int, client: SecClient, identity: int, types: int, sics: int, unresolved: int, started: float) -> None:
    pct = 100.0 if total == 0 else 100.0 * done / total
    elapsed = int(time.monotonic() - started)
    print(
        f"[PROGRESS] year={year} tickers={done}/{total} pct={pct:.1f}% "
        f"requests={client.requests} cache_hits={client.cache_hits} "
        f"identity_events={identity} type_events={types} sic_events={sics} "
        f"unresolved={unresolved} elapsed_s={elapsed}",
        flush=True,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target-year", type=int, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--existing-ticker-cik", type=Path, required=True)
    p.add_argument("--discovery-tickers", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--delay", type=float, default=1.35)
    p.add_argument("--progress-every", type=int, default=10)
    args = p.parse_args()

    year = args.target_year
    start = f"{year - 3}-01-01"
    end = f"{year}-12-31"
    year_start = f"{year}-01-01"
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    filings_dir = out / "primary-sec-filings"
    filings_dir.mkdir(exist_ok=True)

    candidates = load_candidates(args.candidates)
    existing = base.load_existing_ticker_ciks(args.existing_ticker_cik)
    discovery = base.load_discovery_tickers(args.discovery_tickers)
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_ticker[base.norm_ticker(c["ticker"])].append(c)
    tickers = sorted(by_ticker)

    baseline = {
        "candidate_security_episodes": len(candidates),
        "candidate_tickers": len(tickers),
        "unknown_type_observations": sum(c["unknown_type_observations"] for c in candidates),
        "missing_sector_observations": sum(c["missing_sector_observations"] for c in candidates),
    }
    client = SecClient(out / ".http-cache", args.delay, year)
    identity_events: list[dict] = []
    type_events: list[dict] = []
    sic_events: list[dict] = []
    source_rows: list[dict] = []
    unresolved: list[dict] = []
    started = time.monotonic()

    print(
        f"[START] year={year} candidate_episodes={len(candidates)} tickers={len(tickers)} "
        f"source_window={start}..{end} delay_s={args.delay}", flush=True
    )
    progress(year, 0, len(tickers), client, 0, 0, 0, 0, started)

    for ticker_index, ticker in enumerate(tickers, 1):
        ciks = set(existing.get(ticker, set()))
        for c in by_ticker[ticker]:
            ciks.update(c["observed_ciks_set"])
        discovery_only = False
        if not ciks:
            ciks.update(discovery.get(ticker, set()))
            discovery_only = bool(ciks)
        if not ciks:
            for c in by_ticker[ticker]:
                unresolved.append({
                    "target_year": year, "security_id": c["security_id"], "ticker": ticker,
                    "reason": "no_cik_discovery_candidate", "candidate_ciks": "",
                    "observations": c["observations"],
                    "unknown_type_observations": c["unknown_type_observations"],
                    "missing_sector_observations": c["missing_sector_observations"],
                })
        else:
            admitted_for_ticker = False
            for cik in sorted(ciks):
                try:
                    history = load_submission_history(client, cik, start, end)
                except (ReconstructionError, json.JSONDecodeError) as exc:
                    client.failures.append({"url": f"submissions:{cik}", "error": repr(exc)})
                    continue
                for filing in choose_filings(history, year, start, end):
                    accession = filing["accessionNumber"]
                    if not accession:
                        continue
                    url = base.filing_url(cik, accession)
                    try:
                        raw = client.get(url)
                    except ReconstructionError:
                        continue
                    digest = hashlib.sha256(raw).hexdigest()
                    text = raw.decode("utf-8", errors="replace")
                    form = filing["form"].upper()
                    filed = filing["filingDate"]
                    archive_name = f"{cik}_{accession}_{digest[:16]}.txt.gz"
                    archive_path = filings_dir / archive_name
                    if not archive_path.exists():
                        write_gzip_bytes(archive_path, raw)
                    source_rows.append({
                        "filed": filed, "cik": cik, "form": form, "accession": accession,
                        "url": url, "sha256": digest, "bytes": len(raw),
                        "artifact_member": f"primary-sec-filings/{archive_name}",
                    })

                    symbols = {base.norm_ticker(x) for x in base.ISSUER_SYMBOL_RE.findall(text) if base.norm_ticker(x)}
                    ticker_verified = ticker in symbols
                    if ticker_verified:
                        admitted_for_ticker = True
                        identity_events.append({
                            "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                            "form": form, "accession": accession, "source_url": url,
                            "source_sha256": digest, "evidence": "historical_issuerTradingSymbol",
                            "discovery_only_cik_hint": str(discovery_only).lower(),
                        })

                    titles = base.SECURITY_TITLE_RE.findall(text) if form in base.OWNERSHIP_FORMS else []
                    classification, title_evidence = base.classify_titles(titles)
                    if ticker_verified and titles:
                        type_events.append({
                            "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                            "classification": classification, "security_title_evidence": title_evidence,
                            "form": form, "accession": accession, "source_url": url,
                            "source_sha256": digest,
                            "authority": "SEC ownership XML issuerTradingSymbol + securityTitle",
                        })

                    sic_match = base.SIC_RE.search(text)
                    if ticker_verified and sic_match:
                        sic_events.append({
                            "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                            "sic": sic_match.group(1).zfill(4), "form": form, "accession": accession,
                            "source_url": url, "source_sha256": digest,
                            "authority": "SEC complete-submission header STANDARD INDUSTRIAL CLASSIFICATION",
                        })
                    elif sic_match and any(e["ticker"] == ticker and e["cik"] == cik for e in identity_events):
                        sic_events.append({
                            "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                            "sic": sic_match.group(1).zfill(4), "form": form, "accession": accession,
                            "source_url": url, "source_sha256": digest,
                            "authority": "historically-verified ticker/CIK + SEC filing-header SIC",
                        })
            if not admitted_for_ticker:
                for c in by_ticker[ticker]:
                    unresolved.append({
                        "target_year": year, "security_id": c["security_id"], "ticker": ticker,
                        "reason": "candidate_cik_not_verified_by_historical_ticker_evidence",
                        "candidate_ciks": ";".join(sorted(ciks)), "observations": c["observations"],
                        "unknown_type_observations": c["unknown_type_observations"],
                        "missing_sector_observations": c["missing_sector_observations"],
                    })

        if ticker_index % max(1, args.progress_every) == 0 or ticker_index == len(tickers):
            progress(
                year, ticker_index, len(tickers), client, len(identity_events), len(type_events),
                len(sic_events), len(unresolved), started,
            )

    identity_events = dedup(identity_events, ("filed", "ticker", "cik", "accession", "source_sha256"))
    type_events = dedup(type_events, ("filed", "ticker", "cik", "classification", "accession", "source_sha256"))
    sic_events = dedup(sic_events, ("filed", "ticker", "cik", "sic", "accession", "source_sha256"))
    source_rows = dedup(source_rows, ("filed", "cik", "accession", "source_sha256"))

    candidate_rows = [{k: v for k, v in c.items() if k != "observed_ciks_set"} | {"target_year": year} for c in candidates]
    write_csv_gz(out / f"candidate_episodes_{year}.csv.gz", [
        "target_year", "security_id", "ticker", "observations", "unknown_type_observations",
        "missing_sector_observations", "observed_ciks",
    ], candidate_rows)
    write_csv_gz(out / "identity_events.csv.gz", [
        "filed", "usable_after", "ticker", "cik", "form", "accession", "source_url",
        "source_sha256", "evidence", "discovery_only_cik_hint",
    ], identity_events)
    write_csv_gz(out / "security_type_events.csv.gz", [
        "filed", "usable_after", "ticker", "cik", "classification", "security_title_evidence",
        "form", "accession", "source_url", "source_sha256", "authority",
    ], type_events)
    write_csv_gz(out / "sic_events.csv.gz", [
        "filed", "usable_after", "ticker", "cik", "sic", "form", "accession",
        "source_url", "source_sha256", "authority",
    ], sic_events)
    write_csv_gz(out / "source_manifest.csv.gz", [
        "filed", "cik", "form", "accession", "url", "sha256", "bytes", "artifact_member",
    ], source_rows)
    write_csv_gz(out / "unresolved.csv.gz", [
        "target_year", "security_id", "ticker", "reason", "candidate_ciks", "observations",
        "unknown_type_observations", "missing_sector_observations",
    ], unresolved)

    type_counts: dict[str, int] = defaultdict(int)
    for row in type_events:
        type_counts[row["classification"]] += 1
    opening_identity = {(r["ticker"], r["cik"]) for r in identity_events if r["filed"] < year_start}
    opening_type = {
        (r["ticker"], r["cik"]) for r in type_events
        if r["filed"] < year_start and r["classification"] != "unknown"
    }
    opening_sic = {(r["ticker"], r["cik"]) for r in sic_events if r["filed"] < year_start}
    summary = {
        "schema": "backtester.historical-metadata-year-evidence/1",
        "status": "EVIDENCE_HARVEST_COMPLETE",
        "target_year": year,
        "causal_rule": "filed < decision_session",
        "current_sec_ticker_map_role": "discovery-only; never causal authority",
        "baseline": baseline,
        "evidence": {
            "historically_verified_identity_events": len(identity_events),
            "security_type_events": len(type_events),
            "security_type_event_classifications": dict(sorted(type_counts.items())),
            "sic_events": len(sic_events),
            "unique_primary_sec_filings": len(source_rows),
            "opening_year_verified_identity_pairs": len(opening_identity),
            "opening_year_resolved_type_pairs": len(opening_type),
            "opening_year_sic_pairs": len(opening_sic),
            "unresolved_episode_records": len(unresolved),
        },
        "network": {"requests": client.requests, "cache_hits": client.cache_hits, "failures": client.failures},
        "source_window": {"from": start, "through": end},
        "progress_unit": "candidate_tickers",
    }
    (out / "coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "network_failures.json").write_text(json.dumps(client.failures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.rmtree(out / ".http-cache", ignore_errors=True)
    files_out = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}" for p in files_out]
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    progress(year, len(tickers), len(tickers), client, len(identity_events), len(type_events), len(sic_events), len(unresolved), started)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
