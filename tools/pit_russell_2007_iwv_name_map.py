#!/usr/bin/env python3
"""Map June 30 2007 IWV filed holdings names to validated Russell ticker snapshots.

Research diagnostic only. The IWV Schedule of Investments is independent corroboration,
not Russell membership authority. Mapping is deliberately conservative: exact canonical
company-name equality first, then unique source-label prefix matching to accommodate the
known fixed-width truncation in Russell membership PDFs. Ambiguous/unmatched names remain
explicit and are never guessed.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

IWV_PDF_URL = "https://announcements.asx.com.au/asxpdf/20071010/pdf/3151dyspjmvx7w.pdf"
EXPECTED_IWV_PDF_SHA256 = "0804b25a28968f7f82fdc2f8ebd10c80ab453d25716f74811743d5e8616daf2d"
EXPECTED_HOLDINGS_ROWS_SHA256 = "94c3097d6205cb80e710d7a8488ad4be974a1f87b0dfee4443133d7570ce27f1"

FOOTNOTE_RE = re.compile(r"(?:\([a-z]\))+$", re.I)
NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
SPACE_RE = re.compile(r"\s+")
ROW_RE = re.compile(r"^\s{5,}(.+?)\s{2,}([\d,]+)\s+\$?\s*([\d,]+)\s*$", re.M)


@dataclass(frozen=True)
class Holding:
    company: str
    shares: str
    value: str


@dataclass(frozen=True)
class SourceIdentity:
    source_year: int
    ticker: str
    company: str
    canonical_company: str


def strip_iwv_footnotes(name: str) -> str:
    value = name.strip()
    while True:
        new = FOOTNOTE_RE.sub("", value).strip()
        if new == value:
            return value
        value = new


def canonical_company(name: str) -> str:
    value = strip_iwv_footnotes(name).upper()
    # Russell source labels and the filed schedule differ in punctuation and often place
    # a leading article at the end, e.g. "Company (The)". Keep semantic words; normalize
    # only presentation differences.
    value = value.replace("&", " AND ")
    value = re.sub(r"\(THE\)", " THE ", value)
    value = NON_ALNUM_RE.sub(" ", value)
    return SPACE_RE.sub(" ", value).strip()


def fetch_iwv_pdf() -> bytes:
    req = urllib.request.Request(
        IWV_PDF_URL,
        headers={"User-Agent": "stocker-pit-russell-research/1.0 (+https://github.com/flabber1835/stocker)"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = response.read()
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("IWV source is not a PDF")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_IWV_PDF_SHA256:
        raise RuntimeError(f"IWV PDF SHA mismatch: {digest}")
    return payload


def render_iwv_window(payload: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="iwv-2007-") as tmp:
        pdf = Path(tmp) / "source.pdf"
        txt = Path(tmp) / "window.txt"
        pdf.write_bytes(payload)
        proc = subprocess.run(
            ["pdftotext", "-layout", "-f", "160", "-l", "265", str(pdf), str(txt)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pdftotext failed: {proc.stderr[:500]}")
        return txt.read_text(errors="replace")


def extract_holdings(text: str) -> list[Holding]:
    upper = text.upper()
    start = upper.index("ISHARES® RUSSELL 3000 INDEX FUND")
    end = upper.index("ISHARES® RUSSELL 3000 GROWTH INDEX FUND", start)
    section = text[start:end]
    section_upper = section.upper()
    common = section_upper.index("COMMON STOCKS")
    total = section_upper.index("TOTAL COMMON STOCKS", common)
    body = section[common:total]
    rows: list[Holding] = []
    for match in ROW_RE.finditer(body):
        company = " ".join(match.group(1).split())
        folded = company.casefold()
        if any(
            token in folded
            for token in (
                "barclays global",
                "ishares trust",
                "schedule of investments",
                "for personal use only",
                "page ",
            )
        ):
            continue
        rows.append(
            Holding(
                company=company,
                shares=match.group(2).replace(",", ""),
                value=match.group(3).replace(",", ""),
            )
        )
    payload = "".join(f"{r.company}\t{r.shares}\t{r.value}\n" for r in rows).encode()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_HOLDINGS_ROWS_SHA256:
        raise RuntimeError(f"IWV extracted rows SHA mismatch: {digest}")
    if len(rows) != 2976 or len({r.company for r in rows}) != 2976:
        raise RuntimeError(f"unexpected IWV holdings cardinality: rows={len(rows)} unique={len({r.company for r in rows})}")
    return rows


def load_source(path: Path, year: int) -> list[SourceIdentity]:
    rows: list[SourceIdentity] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ticker = (row.get("ticker") or "").strip().upper()
            company = (row.get("company") or "").strip()
            if ticker and company:
                rows.append(SourceIdentity(year, ticker, company, canonical_company(company)))
    return rows


def build_indexes(sources: list[SourceIdentity]):
    exact: dict[str, list[SourceIdentity]] = {}
    for item in sources:
        exact.setdefault(item.canonical_company, []).append(item)
    return exact


def unique_ticker(items: list[SourceIdentity]) -> str | None:
    tickers = sorted({item.ticker for item in items})
    return tickers[0] if len(tickers) == 1 else None


def prefix_candidates(name: str, sources: list[SourceIdentity]) -> list[SourceIdentity]:
    # Source labels are visibly truncated by their PDF column width. Accept prefix relation
    # only when the shorter canonical side is reasonably identifying; never fuzzy-edit names.
    out: list[SourceIdentity] = []
    for item in sources:
        source = item.canonical_company
        shorter = min(len(name), len(source))
        if shorter < 10:
            continue
        if name.startswith(source) or source.startswith(name):
            out.append(item)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--russell-2006", type=Path, required=True)
    parser.add_argument("--russell-2010", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    holdings = extract_holdings(render_iwv_window(fetch_iwv_pdf()))
    sources = load_source(args.russell_2006, 2006) + load_source(args.russell_2010, 2010)
    exact_index = build_indexes(sources)

    mapped = []
    ambiguous = []
    unmatched = []
    method_counts: dict[str, int] = {}

    for holding in holdings:
        canonical = canonical_company(holding.company)
        exact = exact_index.get(canonical, [])
        ticker = unique_ticker(exact)
        if ticker:
            method = "exact_canonical"
            candidates = exact
        else:
            candidates = prefix_candidates(canonical, sources)
            ticker = unique_ticker(candidates)
            method = "unique_truncation_prefix" if ticker else ""

        if ticker:
            method_counts[method] = method_counts.get(method, 0) + 1
            mapped.append(
                {
                    "iwv_company": holding.company,
                    "canonical_company": canonical,
                    "ticker": ticker,
                    "method": method,
                    "source_matches": [asdict(x) for x in candidates],
                }
            )
        elif candidates or exact:
            pool = exact if exact else candidates
            ambiguous.append(
                {
                    "iwv_company": holding.company,
                    "canonical_company": canonical,
                    "candidate_tickers": sorted({x.ticker for x in pool}),
                    "source_matches": [asdict(x) for x in pool],
                }
            )
        else:
            unmatched.append(
                {
                    "iwv_company": holding.company,
                    "canonical_company": canonical,
                }
            )

    ticker_counts: dict[str, int] = {}
    for row in mapped:
        ticker_counts[row["ticker"]] = ticker_counts.get(row["ticker"], 0) + 1
    duplicate_mapped_tickers = {k: v for k, v in sorted(ticker_counts.items()) if v > 1}

    result = {
        "schema": 1,
        "source_role": "independent IWV June 30 2007 filed holdings mapping diagnostic; not Russell membership authority",
        "iwv_source_url": IWV_PDF_URL,
        "iwv_pdf_sha256": EXPECTED_IWV_PDF_SHA256,
        "iwv_holdings_rows_sha256": EXPECTED_HOLDINGS_ROWS_SHA256,
        "iwv_holding_count": len(holdings),
        "validated_russell_source_years": [2006, 2010],
        "mapping_methods": {
            "exact_canonical": "same normalized company label after punctuation/article/footnote normalization",
            "unique_truncation_prefix": "unique ticker where validated Russell fixed-width company label is a >=10-character prefix relation; no fuzzy edit",
        },
        "method_counts": method_counts,
        "mapped_count": len(mapped),
        "ambiguous_count": len(ambiguous),
        "unmatched_count": len(unmatched),
        "duplicate_mapped_tickers": duplicate_mapped_tickers,
        "mapped": mapped,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print("IWV holdings", len(holdings))
    print("mapped", len(mapped), method_counts)
    print("ambiguous", len(ambiguous))
    print("unmatched", len(unmatched))
    print("duplicate_mapped_tickers", len(duplicate_mapped_tickers), duplicate_mapped_tickers)
    print("=== AMBIGUOUS ===")
    for row in ambiguous:
        print(json.dumps(row, sort_keys=True))
    print("=== UNMATCHED ===")
    for row in unmatched:
        print(row["iwv_company"], "=>", row["canonical_company"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
