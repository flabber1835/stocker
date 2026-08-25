#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEC_DIR = ROOT / "sec"
PIT_DIR = ROOT / "PIT input data"
TICKERS_ZIP = ROOT / "sharadar" / "SHARADAR_TICKERS.zip"
BUYS = ROOT / "research" / "sentinel-fastgate" / "experiments" / "2026-08-25-pit-vs-full-c" / "recovered" / "terminal_issuer_corrected" / "output" / "executed_buys.csv"

COMMON_PATTERNS = [
    re.compile(r"\bcommon\s+(stock|shares?)\b", re.I),
    re.compile(r"\bclass\s+[a-z0-9]+\s+common\b", re.I),
    re.compile(r"\bordinary\s+shares?\b", re.I),
    re.compile(r"\bordinary\s+stock\b", re.I),
]
EXCLUDE_PATTERNS = [
    re.compile(r"preferred", re.I),
    re.compile(r"warrant", re.I),
    re.compile(r"option", re.I),
    re.compile(r"restricted\s+stock\s+unit|\brsu\b", re.I),
    re.compile(r"phantom", re.I),
    re.compile(r"convertible", re.I),
]


def norm(s: str | None) -> str:
    return (s or "").strip()


def pick(headers, names):
    canon = {re.sub(r"[^a-z0-9]", "", h.lower()): h for h in headers}
    for n in names:
        k = re.sub(r"[^a-z0-9]", "", n.lower())
        if k in canon:
            return canon[k]
    return None


def parse_table(raw: bytes):
    text = raw.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    return csv.DictReader(io.StringIO(text), delimiter=delim)


def classify_title(title: str):
    if not title:
        return False
    if any(p.search(title) for p in EXCLUDE_PATTERNS):
        return False
    return any(p.search(title) for p in COMMON_PATTERNS)


def load_legacy_tickers():
    with zipfile.ZipFile(TICKERS_ZIP) as z:
        names = z.namelist()
        target = next(n for n in names if n.lower().endswith(("tickers.csv", "tickers.tsv")))
        r = parse_table(z.read(target))
        out = {}
        for row in r:
            t = norm(row.get("ticker"))
            cat = norm(row.get("category"))
            if not t:
                continue
            out[t] = cat
        return out


def load_executed_buys():
    if not BUYS.exists():
        return []
    with BUYS.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = []
        for row in r:
            t = norm(row.get("ticker"))
            d = norm(row.get("date") or row.get("session") or row.get("entry_date"))
            if t:
                rows.append((t, d))
        return rows


def main():
    zips = sorted(SEC_DIR.glob("*_form345.zip"))
    if not zips:
        raise SystemExit("No SEC Form 3/4/5 archives found")

    schema_counter = Counter()
    member_counter = Counter()
    title_counter = Counter()
    evidence = []
    first_common = {}
    accession_meta = {}
    archive_stats = []

    for zp in zips:
        quarter = zp.stem.replace("_form345", "")
        with zipfile.ZipFile(zp) as z:
            members = z.namelist()
            for m in members:
                member_counter[Path(m).name.lower()] += 1

            # First pass: locate submission-like table and build accession -> (filed, symbol, cik)
            local_meta = {}
            for m in members:
                base = Path(m).name.lower()
                if "submission" not in base:
                    continue
                r = parse_table(z.read(m))
                headers = r.fieldnames or []
                a = pick(headers, ["accession_number", "accessionnumber", "accession"])
                fd = pick(headers, ["filing_date", "filingdate", "filed"])
                sy = pick(headers, ["issuer_trading_symbol", "issuertradingsymbol", "issuersymbol"])
                cik = pick(headers, ["issuer_cik", "issuercik"])
                if not (a and fd and sy):
                    continue
                for row in r:
                    acc = norm(row.get(a))
                    sym = norm(row.get(sy)).upper()
                    filed = norm(row.get(fd))
                    c = norm(row.get(cik)) if cik else ""
                    if acc and sym and filed:
                        local_meta[acc] = (filed, sym, c)
                        accession_meta[acc] = (filed, sym, c)

            q_titles = 0
            q_common = 0
            q_joined = 0
            # Second pass: inspect non-derivative holdings/transactions for security titles
            for m in members:
                base = Path(m).name.lower()
                if not ("nonderiv" in base or "non_deriv" in base or "non-deriv" in base):
                    continue
                r = parse_table(z.read(m))
                headers = r.fieldnames or []
                schema_counter[(base, tuple(headers))] += 1
                a = pick(headers, ["accession_number", "accessionnumber", "accession"])
                st = pick(headers, ["security_title", "securitytitle", "security_title_value", "securitytitlevalue"])
                if not (a and st):
                    continue
                for row in r:
                    acc = norm(row.get(a))
                    title = norm(row.get(st))
                    if not title:
                        continue
                    q_titles += 1
                    title_counter[title] += 1
                    meta = local_meta.get(acc) or accession_meta.get(acc)
                    if not meta:
                        continue
                    q_joined += 1
                    filed, sym, cik = meta
                    is_common = classify_title(title)
                    if is_common:
                        q_common += 1
                        prev = first_common.get(sym)
                        if prev is None or filed < prev[0]:
                            first_common[sym] = (filed, title, cik, quarter)
                        evidence.append((sym, filed, cik, title, quarter, acc))
            archive_stats.append({"quarter": quarter, "members": len(members), "submission_rows": len(local_meta), "security_title_rows": q_titles, "joined_title_rows": q_joined, "positive_common_rows": q_common})

    legacy = load_legacy_tickers()
    legacy_common = {t for t, cat in legacy.items() if "common stock" in cat.lower() and "warrant" not in cat.lower() and "preferred" not in cat.lower()}
    evidence_tickers = set(first_common)
    common_covered = legacy_common & evidence_tickers

    buys = load_executed_buys()
    buy_tickers = {t for t, _ in buys}
    buy_covered_tickers = buy_tickers & evidence_tickers
    buy_rows_causal = 0
    buy_rows_total_dated = 0
    buy_rows_missing = []
    for t, d in buys:
        if not d:
            continue
        buy_rows_total_dated += 1
        ev = first_common.get(t)
        if ev and ev[0] < d:
            buy_rows_causal += 1
        else:
            buy_rows_missing.append((t, d, ev[0] if ev else ""))

    out_csv = PIT_DIR / "SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz"
    with gzip.open(out_csv, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "filed", "cik", "security_title", "source_quarter", "accession"])
        for row in sorted(evidence, key=lambda x: (x[0], x[1], x[5])):
            w.writerow(row)

    missing_csv = PIT_DIR / "SEC_SECURITY_TYPE_BUY_COVERAGE_GAPS.csv"
    with missing_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "buy_date", "first_positive_common_filing"])
        w.writerows(sorted(buy_rows_missing))

    report = {
        "archives": len(zips),
        "archive_range": [zips[0].name, zips[-1].name],
        "distinct_positive_common_tickers": len(evidence_tickers),
        "legacy_common_tickers": len(legacy_common),
        "legacy_common_ticker_coverage": len(common_covered),
        "legacy_common_ticker_coverage_pct": (len(common_covered) / len(legacy_common) if legacy_common else None),
        "executed_buy_tickers": len(buy_tickers),
        "executed_buy_tickers_with_any_positive_evidence": len(buy_covered_tickers),
        "executed_buy_ticker_coverage_pct": (len(buy_covered_tickers) / len(buy_tickers) if buy_tickers else None),
        "executed_buy_rows_with_dates": buy_rows_total_dated,
        "executed_buy_rows_causally_covered_before_buy": buy_rows_causal,
        "executed_buy_row_causal_coverage_pct": (buy_rows_causal / buy_rows_total_dated if buy_rows_total_dated else None),
        "executed_buy_rows_not_causally_covered": len(buy_rows_missing),
        "top_security_titles": title_counter.most_common(100),
        "archive_stats": archive_stats,
        "classification_rule": {
            "positive_only": True,
            "rule": "A symbol becomes common-stock-eligible only after a filed Form 3/4/5 non-derivative security title positively matches common/ordinary equity and matches the submission issuer trading symbol. Negative instrument titles do not classify the issuer symbol as non-common.",
            "decision_cutoff": "evidence filing date must be strictly earlier than decision/buy date",
            "unknown_policy": "unknown remains ineligible"
        }
    }
    (PIT_DIR / "SEC_SECURITY_TYPE_COVERAGE.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    md = [
        "# Orion SEC security-type coverage analysis",
        "",
        f"Archives inspected: **{len(zips)}** ({zips[0].name} through {zips[-1].name}).",
        "",
        "## Coverage",
        "",
        f"- Positive common-stock symbols from Form 3/4/5 security-title evidence: **{len(evidence_tickers):,}**",
        f"- Legacy Sharadar common-stock symbols: **{len(legacy_common):,}**",
        f"- Legacy common-stock ticker coverage: **{len(common_covered):,}/{len(legacy_common):,} ({report['legacy_common_ticker_coverage_pct']:.2%})**" if legacy_common else "- Legacy common-stock ticker coverage: n/a",
        f"- Authoritative executed-buy tickers with any positive evidence: **{len(buy_covered_tickers):,}/{len(buy_tickers):,} ({report['executed_buy_ticker_coverage_pct']:.2%})**" if buy_tickers else "- Executed-buy ticker coverage: n/a",
        f"- Executed-buy rows causally covered before buy date: **{buy_rows_causal:,}/{buy_rows_total_dated:,} ({report['executed_buy_row_causal_coverage_pct']:.2%})**" if buy_rows_total_dated else "- Executed-buy row causal coverage: n/a",
        f"- Executed-buy rows lacking prior positive evidence: **{len(buy_rows_missing):,}**",
        "",
        "## PIT rule",
        "",
        "A ticker becomes eligible as common stock only after an SEC filing whose issuer trading symbol matches the ticker and whose non-derivative security title positively identifies common/ordinary equity. Preferred, warrant, option, RSU, phantom, and convertible titles are not positive evidence. Absence of evidence is **unknown/ineligible**. Filing-date evidence must be strictly earlier than the Orion decision session.",
        "",
        "## Interpretation",
        "",
        "This is a coverage diagnostic, not yet a certification. Form 3/4/5 security titles can provide causal positive evidence, but final use depends on whether candidate/session coverage is sufficiently complete. Executed-buy coverage is the first economic materiality gate; full candidate/session coverage remains the promotion gate.",
    ]
    (PIT_DIR / "SEC_SECURITY_TYPE_COVERAGE.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({k: report[k] for k in report if k not in {"top_security_titles", "archive_stats"}}, indent=2))


if __name__ == "__main__":
    main()
