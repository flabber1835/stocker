#!/usr/bin/env python3
"""Harvest causally dated SEC evidence for the 2006 historical simulation.

This is evidence reconstruction, not strategy code.  Current SEC ticker metadata may
be used only as a *discovery hint*.  A ticker/CIK relationship is admitted only
when a historically filed primary SEC document independently contains the ticker.
Economic consumers must apply the strict-prior rule ``filed < decision_session``.

The tool is deliberately fail-closed: ambiguous security titles remain ``unknown``;
trading activity is never treated as proof of common-stock status; and every
admitted row retains the source URL and SHA-256 of the SEC filing bytes.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

USER_AGENT = "stocker-historical-metadata-certification/1.0 contact=m.bron01@gmail.com"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
START = "2003-01-01"
END = "2006-12-31"
OWNERSHIP_FORMS = {"3", "3/A", "4", "4/A", "5", "5/A"}
PERIODIC_FORMS = {
    "10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A",
    "8-K", "8-K/A", "S-1", "S-1/A", "F-1", "F-1/A", "10", "10/A",
}
COMMON_PATTERNS = (
    re.compile(r"\bcommon\s+(?:stock|shares?)\b", re.I),
    re.compile(r"\bordinary\s+shares?\b", re.I),
    re.compile(r"\bcommon\s+shares?\s+of\s+beneficial\s+interest\b", re.I),
)
NON_COMMON_PATTERNS = (
    re.compile(r"\bpreferred\s+(?:stock|shares?)\b", re.I),
    re.compile(r"\bwarrants?\b", re.I),
    re.compile(r"\bunits?\b", re.I),
    re.compile(r"\brights?\b", re.I),
    re.compile(r"\bconvertible\s+(?:notes?|debentures?|debt)\b", re.I),
)
SIC_RE = re.compile(r"STANDARD\s+INDUSTRIAL\s+CLASSIFICATION\s*:\s*[^\[]*\[(\d{3,4})\]", re.I)
ISSUER_SYMBOL_RE = re.compile(r"<issuerTradingSymbol>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</issuerTradingSymbol>", re.I)
SECURITY_TITLE_RE = re.compile(r"<securityTitle>.*?<value>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</value>.*?</securityTitle>", re.I | re.S)


class ReconstructionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    security_id: str
    ticker: str
    observations: int
    unknown_type_observations: int
    missing_sector_observations: int
    observed_ciks: tuple[str, ...]


class SecClient:
    def __init__(self, cache: Path, delay: float = 0.12):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay = delay
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
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        last: Exception | None = None
        for attempt in range(5):
            try:
                time.sleep(self.delay)
                with urllib.request.urlopen(req, timeout=45) as response:
                    data = response.read()
                path.write_bytes(data)
                self.requests += 1
                return data
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                time.sleep(min(8.0, 0.5 * (2 ** attempt)))
        self.failures.append({"url": url, "error": repr(last)})
        raise ReconstructionError(f"SEC fetch failed after retries: {url}: {last}")

    def json(self, url: str) -> dict:
        return json.loads(self.get(url).decode("utf-8"))


def norm_ticker(value: str) -> str:
    return (value or "").strip().upper()


def norm_cik(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(10) if digits else ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def observation_files(dataset: Path) -> list[Path]:
    required = {"session", "security_id", "ticker", "issuer_id", "security_type", "sic", "ff12"}
    result: list[Path] = []
    for path in sorted(dataset.rglob("*.csv.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
                header = next(csv.reader(fh), [])
        except (OSError, UnicodeDecodeError):
            continue
        if required.issubset(set(header)):
            result.append(path)
    if not result:
        raise ReconstructionError("could not locate canonical observation partitions")
    return result


def extract_candidates(dataset: Path) -> tuple[list[Candidate], dict]:
    by_key: dict[tuple[str, str], dict] = {}
    sessions: set[str] = set()
    total_rows = 0
    for path in observation_files(dataset):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                session = row["session"]
                if not session.startswith("2006-"):
                    continue
                total_rows += 1
                sessions.add(session)
                ticker = norm_ticker(row.get("ticker", ""))
                sid = (row.get("security_id") or "").strip()
                if not ticker or not sid:
                    continue
                key = (sid, ticker)
                rec = by_key.setdefault(key, {"obs": 0, "unknown": 0, "sector": 0, "ciks": set()})
                rec["obs"] += 1
                stype = (row.get("security_type") or "").strip().lower()
                if not stype or stype == "unknown":
                    rec["unknown"] += 1
                if not (row.get("sic") or "").strip() or not (row.get("ff12") or "").strip():
                    rec["sector"] += 1
                cik = norm_cik(row.get("issuer_id", ""))
                if cik:
                    rec["ciks"].add(cik)
    candidates = [
        Candidate(sid, ticker, rec["obs"], rec["unknown"], rec["sector"], tuple(sorted(rec["ciks"])))
        for (sid, ticker), rec in sorted(by_key.items())
        if rec["unknown"] or rec["sector"]
    ]
    return candidates, {
        "candidate_session_rows_2006": total_rows,
        "sessions_2006": len(sessions),
        "candidate_security_episodes": len(by_key),
        "episodes_needing_type_or_sector_enrichment": len(candidates),
        "unknown_type_observations": sum(c.unknown_type_observations for c in candidates),
        "missing_sector_observations": sum(c.missing_sector_observations for c in candidates),
    }


def load_existing_ticker_ciks(path: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    if not path.exists():
        return result
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            ticker = norm_ticker(row.get("ticker") or row.get("issuer_trading_symbol") or "")
            cik = norm_cik(row.get("issuer_cik") or row.get("cik") or "")
            if ticker and cik:
                result[ticker].add(cik)
    return result


def load_discovery_tickers(path: Path) -> dict[str, set[str]]:
    """Current SEC mapping is discovery-only and never emitted as causal evidence."""
    result: dict[str, set[str]] = defaultdict(set)
    if not path.exists():
        return result
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.values() if isinstance(payload, dict) else payload
    for row in values:
        if not isinstance(row, dict):
            continue
        ticker = norm_ticker(row.get("ticker", ""))
        cik = norm_cik(row.get("cik_str", ""))
        if ticker and cik:
            result[ticker].add(cik)
    return result


def filing_rows(payload: dict) -> Iterator[dict[str, str]]:
    recent = payload.get("filings", {}).get("recent") if isinstance(payload.get("filings"), dict) else None
    table = recent if isinstance(recent, dict) else payload
    if not isinstance(table, dict) or "accessionNumber" not in table:
        return
    keys = ["accessionNumber", "filingDate", "form", "primaryDocument"]
    columns = {k: table.get(k, []) for k in keys}
    n = len(columns["accessionNumber"])
    for i in range(n):
        row = {k: str(columns[k][i] if i < len(columns[k]) else "") for k in keys}
        yield row


def load_submission_history(client: SecClient, cik: str) -> list[dict[str, str]]:
    url = f"{SEC_SUBMISSIONS}/CIK{cik}.json"
    root = client.json(url)
    rows = list(filing_rows(root))
    files = root.get("filings", {}).get("files", []) if isinstance(root.get("filings"), dict) else []
    for meta in files:
        if not isinstance(meta, dict):
            continue
        start = str(meta.get("filingFrom") or "")
        end = str(meta.get("filingTo") or "")
        if start and start > END:
            continue
        if end and end < START:
            continue
        name = str(meta.get("name") or "")
        if not name:
            continue
        try:
            rows.extend(filing_rows(client.json(f"{SEC_SUBMISSIONS}/{name}")))
        except ReconstructionError:
            continue
    unique = {(r["accessionNumber"], r["filingDate"], r["form"], r["primaryDocument"]): r for r in rows}
    return sorted(unique.values(), key=lambda r: (r["filingDate"], r["accessionNumber"]))


def choose_filings(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    eligible = [r for r in rows if START <= r["filingDate"] <= END and r["form"].upper() in OWNERSHIP_FORMS | PERIODIC_FORMS]
    ownership = [r for r in eligible if r["form"].upper() in OWNERSHIP_FORMS]
    periodic = [r for r in eligible if r["form"].upper() in PERIODIC_FORMS]
    selected: dict[str, dict[str, str]] = {}

    pre_own = [r for r in ownership if r["filingDate"] < "2006-01-01"]
    in_own = [r for r in ownership if r["filingDate"] >= "2006-01-01"]
    for r in ((pre_own[-1:] if pre_own else []) + (in_own[:1] if in_own else []) + (in_own[-1:] if len(in_own) > 1 else [])):
        selected[r["accessionNumber"]] = r

    # Periodic filings are sparse and provide the strongest historical SIC/header evidence.
    for r in periodic:
        if r["filingDate"] >= "2005-01-01" or r is periodic[-1]:
            selected[r["accessionNumber"]] = r
    if periodic:
        pre = [r for r in periodic if r["filingDate"] < "2006-01-01"]
        if pre:
            selected[pre[-1]["accessionNumber"]] = pre[-1]
    return sorted(selected.values(), key=lambda r: (r["filingDate"], r["accessionNumber"]))


def filing_url(cik: str, accession: str) -> str:
    cik_int = str(int(cik))
    compact = accession.replace("-", "")
    return f"{SEC_ARCHIVES}/{cik_int}/{compact}/{accession}.txt"


def clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def classify_titles(titles: list[str]) -> tuple[str, str]:
    normalized = [clean_title(t) for t in titles if clean_title(t)]
    common = [t for t in normalized if any(p.search(t) for p in COMMON_PATTERNS)]
    non_common = [t for t in normalized if any(p.search(t) for p in NON_COMMON_PATTERNS)]
    if common and not non_common:
        return "common", " | ".join(sorted(set(common)))
    if non_common and not common:
        return "non_common", " | ".join(sorted(set(non_common)))
    return "unknown", " | ".join(sorted(set(normalized)))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def deterministic_gzip(path: Path) -> Path:
    target = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as src, target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    path.unlink()
    return target


def reconstruct(args: argparse.Namespace) -> dict:
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    filings_dir = out / "primary-sec-filings"
    filings_dir.mkdir(exist_ok=True)

    candidates, baseline = extract_candidates(args.canonical_dataset)
    existing = load_existing_ticker_ciks(args.existing_ticker_cik)
    discovery = load_discovery_tickers(args.discovery_tickers)

    client = SecClient(out / ".http-cache", delay=args.delay)
    identity_events: list[dict] = []
    type_events: list[dict] = []
    sic_events: list[dict] = []
    source_rows: list[dict] = []
    unresolved: list[dict] = []

    by_ticker: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_ticker[c.ticker].append(c)

    for ticker in sorted(by_ticker):
        ciks = set(existing.get(ticker, set()))
        for c in by_ticker[ticker]:
            ciks.update(c.observed_ciks)
        discovery_only = False
        if not ciks:
            ciks.update(discovery.get(ticker, set()))
            discovery_only = bool(ciks)
        if not ciks:
            for c in by_ticker[ticker]:
                unresolved.append({
                    "security_id": c.security_id, "ticker": ticker,
                    "reason": "no_cik_discovery_candidate", "candidate_ciks": "",
                    "observations": c.observations,
                    "unknown_type_observations": c.unknown_type_observations,
                    "missing_sector_observations": c.missing_sector_observations,
                })
            continue

        admitted_for_ticker = False
        for cik in sorted(ciks):
            try:
                history = load_submission_history(client, cik)
            except (ReconstructionError, json.JSONDecodeError) as exc:
                client.failures.append({"url": f"submissions:{cik}", "error": repr(exc)})
                continue
            for filing in choose_filings(history):
                accession = filing["accessionNumber"]
                if not accession:
                    continue
                url = filing_url(cik, accession)
                try:
                    raw = client.get(url)
                except ReconstructionError:
                    continue
                digest = sha256_bytes(raw)
                text = raw.decode("utf-8", errors="replace")
                form = filing["form"].upper()
                filed = filing["filingDate"]
                archive_name = f"{cik}_{accession}_{digest[:16]}.txt.gz"
                archive_path = filings_dir / archive_name
                if not archive_path.exists():
                    with gzip.open(archive_path, "wb", mtime=0) if False else archive_path.open("wb") as _:
                        pass
                    # gzip.GzipFile is used explicitly for deterministic mtime.
                    with archive_path.open("wb") as raw_out:
                        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, compresslevel=9, mtime=0) as gz:
                            gz.write(raw)
                source_rows.append({
                    "filed": filed, "cik": cik, "form": form, "accession": accession,
                    "url": url, "sha256": digest, "bytes": len(raw), "artifact_member": f"primary-sec-filings/{archive_name}",
                })

                symbols = {norm_ticker(x) for x in ISSUER_SYMBOL_RE.findall(text) if norm_ticker(x)}
                ticker_verified = ticker in symbols
                if ticker_verified:
                    admitted_for_ticker = True
                    identity_events.append({
                        "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                        "form": form, "accession": accession, "source_url": url,
                        "source_sha256": digest, "evidence": "historical_issuerTradingSymbol",
                        "discovery_only_cik_hint": str(discovery_only).lower(),
                    })

                titles = SECURITY_TITLE_RE.findall(text) if form in OWNERSHIP_FORMS else []
                classification, title_evidence = classify_titles(titles)
                if ticker_verified and titles:
                    type_events.append({
                        "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                        "classification": classification, "security_title_evidence": title_evidence,
                        "form": form, "accession": accession, "source_url": url, "source_sha256": digest,
                        "authority": "SEC ownership XML issuerTradingSymbol + securityTitle",
                    })

                sic_match = SIC_RE.search(text)
                if ticker_verified and sic_match:
                    sic_events.append({
                        "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                        "sic": sic_match.group(1).zfill(4), "form": form, "accession": accession,
                        "source_url": url, "source_sha256": digest,
                        "authority": "SEC complete-submission header STANDARD INDUSTRIAL CLASSIFICATION",
                    })
                elif sic_match and any(e["ticker"] == ticker and e["cik"] == cik for e in identity_events):
                    # Identity was independently established by a historical ownership filing;
                    # SIC is issuer-level and may therefore come from another filing of that CIK.
                    sic_events.append({
                        "filed": filed, "usable_after": filed, "ticker": ticker, "cik": cik,
                        "sic": sic_match.group(1).zfill(4), "form": form, "accession": accession,
                        "source_url": url, "source_sha256": digest,
                        "authority": "historically-verified ticker/CIK + SEC filing-header SIC",
                    })

        if not admitted_for_ticker:
            for c in by_ticker[ticker]:
                unresolved.append({
                    "security_id": c.security_id, "ticker": ticker,
                    "reason": "candidate_cik_not_verified_by_historical_ticker_evidence",
                    "candidate_ciks": ";".join(sorted(ciks)), "observations": c.observations,
                    "unknown_type_observations": c.unknown_type_observations,
                    "missing_sector_observations": c.missing_sector_observations,
                })

    # De-duplicate exact evidence rows deterministically.
    def dedup(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
        return [dict(zip(keys, key)) | next(r for r in rows if tuple(str(r.get(k, "")) for k in keys) == key)
                for key in sorted({tuple(str(r.get(k, "")) for k in keys) for r in rows})]

    identity_events = dedup(identity_events, ("filed", "ticker", "cik", "accession", "source_sha256")) if identity_events else []
    type_events = dedup(type_events, ("filed", "ticker", "cik", "classification", "accession", "source_sha256")) if type_events else []
    sic_events = dedup(sic_events, ("filed", "ticker", "cik", "sic", "accession", "source_sha256")) if sic_events else []
    source_rows = dedup(source_rows, ("filed", "cik", "accession", "source_sha256")) if source_rows else []

    write_csv(out / "candidate_episodes_2006.csv", [
        "security_id", "ticker", "observations", "unknown_type_observations", "missing_sector_observations", "observed_ciks"
    ], [c.__dict__ | {"observed_ciks": ";".join(c.observed_ciks)} for c in candidates])
    write_csv(out / "identity_events.csv", [
        "filed", "usable_after", "ticker", "cik", "form", "accession", "source_url", "source_sha256", "evidence", "discovery_only_cik_hint"
    ], identity_events)
    write_csv(out / "security_type_events.csv", [
        "filed", "usable_after", "ticker", "cik", "classification", "security_title_evidence", "form", "accession", "source_url", "source_sha256", "authority"
    ], type_events)
    write_csv(out / "sic_events.csv", [
        "filed", "usable_after", "ticker", "cik", "sic", "form", "accession", "source_url", "source_sha256", "authority"
    ], sic_events)
    write_csv(out / "source_manifest.csv", [
        "filed", "cik", "form", "accession", "url", "sha256", "bytes", "artifact_member"
    ], source_rows)
    write_csv(out / "unresolved.csv", [
        "security_id", "ticker", "reason", "candidate_ciks", "observations", "unknown_type_observations", "missing_sector_observations"
    ], unresolved)

    for name in ("candidate_episodes_2006.csv", "identity_events.csv", "security_type_events.csv", "sic_events.csv", "source_manifest.csv", "unresolved.csv"):
        deterministic_gzip(out / name)

    type_counts: dict[str, int] = defaultdict(int)
    for row in type_events:
        type_counts[row["classification"]] += 1
    pre2006_identity = {(r["ticker"], r["cik"]) for r in identity_events if r["filed"] < "2006-01-01"}
    pre2006_type = {(r["ticker"], r["cik"]) for r in type_events if r["filed"] < "2006-01-01" and r["classification"] != "unknown"}
    pre2006_sic = {(r["ticker"], r["cik"]) for r in sic_events if r["filed"] < "2006-01-01"}
    summary = {
        "schema": "backtester.historical-metadata-2006-evidence/1",
        "status": "EVIDENCE_HARVEST_COMPLETE",
        "causal_rule": "filed < decision_session",
        "current_sec_ticker_map_role": "discovery-only; never causal authority",
        "baseline": baseline,
        "evidence": {
            "historically_verified_identity_events": len(identity_events),
            "security_type_events": len(type_events),
            "security_type_event_classifications": dict(sorted(type_counts.items())),
            "sic_events": len(sic_events),
            "unique_primary_sec_filings": len(source_rows),
            "opening_2006_verified_identity_pairs": len(pre2006_identity),
            "opening_2006_resolved_type_pairs": len(pre2006_type),
            "opening_2006_sic_pairs": len(pre2006_sic),
            "unresolved_episode_records": len(unresolved),
        },
        "network": {"requests": client.requests, "cache_hits": client.cache_hits, "failures": client.failures},
        "source_window": {"from": START, "through": END},
    }
    (out / "coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "network_failures.json").write_text(json.dumps(client.failures, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # HTTP cache is transport scratch. Primary bytes retained above are the evidence.
    import shutil
    shutil.rmtree(out / ".http-cache", ignore_errors=True)

    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}" for p in files]
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-dataset", type=Path, required=True)
    p.add_argument("--existing-ticker-cik", type=Path, required=True)
    p.add_argument("--discovery-tickers", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--delay", type=float, default=0.12)
    args = p.parse_args()
    summary = reconstruct(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    # Network failures are retained and quantified; they do not silently become evidence.
    # A later admission phase decides whether remaining gaps are material.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
