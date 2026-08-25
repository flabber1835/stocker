#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import html
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIT_DIR = ROOT / "PIT input data"
GAPS = PIT_DIR / "SEC_SECURITY_TYPE_BUY_COVERAGE_GAPS.csv"
TICKERS_ZIP = ROOT / "sharadar" / "SHARADAR_TICKERS.zip"
IDENTITY = ROOT / "research" / "sentinel-fastgate" / "pit-evidence" / "generated" / "symbol_cik_evidence.csv.gz"
OUT = PIT_DIR / "SEC_COVERPAGE_SECURITY_TYPE_EVIDENCE.csv"
UNRESOLVED = PIT_DIR / "SEC_COVERPAGE_SECURITY_TYPE_UNRESOLVED.csv"
REPORT = PIT_DIR / "SEC_COVERPAGE_SECURITY_TYPE_REPORT.json"

UA = "Orion-PIT-research/1.0 flabber1835@users.noreply.github.com"
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A", "S-1", "S-1/A", "F-1", "F-1/A"}
COMMON_RE = re.compile(r"\b(common\s+(stock|shares?)|ordinary\s+(shares?|stock)|class\s+[a-z0-9]+\s+common)\b", re.I)
BAD_RE = re.compile(r"\b(preferred|warrant|option|restricted\s+stock\s+unit|\brsu\b|phantom|convertible)\b", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def get(url: str, retries: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            time.sleep(0.12)
            return data
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in {403, 404}:
                if e.code == 404:
                    raise
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(url)


def parse_delimited(raw: bytes):
    text = raw.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    return csv.DictReader(io.StringIO(text), delimiter=delim)


def load_tickers():
    with zipfile.ZipFile(TICKERS_ZIP) as z:
        names = z.namelist()
        target = next(n for n in names if "ticker" in Path(n).name.lower() and n.lower().endswith((".csv", ".tsv")))
        out = {}
        for row in parse_delimited(z.read(target)):
            t = (row.get("ticker") or "").strip().upper()
            if t:
                out[t] = row
        return out


def norm_cik(v: str | None) -> str:
    s = re.sub(r"\D", "", v or "")
    return s.zfill(10) if s else ""


def cik_hint_from_tickers(row: dict) -> str:
    s = row.get("secfilings") or ""
    for pat in [r"(?i)CIK(?:=|%3D)(\d{1,10})", r"/data/(\d{1,10})/", r"CIK(\d{10})"]:
        m = re.search(pat, s)
        if m:
            return norm_cik(m.group(1))
    return ""


def load_identity():
    out = {}
    if not IDENTITY.exists():
        return out
    with gzip.open(IDENTITY, "rt", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            t = (row.get("ticker") or row.get("symbol") or "").strip().upper()
            d = (row.get("filing_date") or row.get("filed") or row.get("date") or "").strip()
            cik = norm_cik(row.get("issuer_cik") or row.get("cik"))
            if t and d and cik:
                out.setdefault(t, []).append((d, cik))
    for t in out:
        out[t].sort()
    return out


def causal_identity_cik(identity, ticker: str, buy_date: str) -> str:
    vals = [c for d, c in identity.get(ticker, []) if d < buy_date]
    return vals[-1] if vals else ""


def current_sec_map():
    raw = get("https://www.sec.gov/files/company_tickers.json")
    obj = json.loads(raw)
    out = {}
    for v in obj.values():
        t = str(v.get("ticker") or "").upper()
        cik = norm_cik(str(v.get("cik_str") or ""))
        if t and cik:
            out[t] = cik
    return out


def filing_rows(cik10: str):
    base = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    obj = json.loads(get(base))
    rows = []
    recent = obj.get("filings", {}).get("recent", {})
    keys = list(recent.keys())
    if keys:
        n = len(recent.get("accessionNumber", []))
        for i in range(n):
            rows.append({k: recent.get(k, [None] * n)[i] if i < len(recent.get(k, [])) else None for k in keys})
    for item in obj.get("filings", {}).get("files", []):
        name = item.get("name")
        if not name:
            continue
        older = json.loads(get("https://data.sec.gov/submissions/" + name))
        keys = list(older.keys())
        n = len(older.get("accessionNumber", []))
        for i in range(n):
            rows.append({k: older.get(k, [None] * n)[i] if i < len(older.get(k, [])) else None for k in keys})
    return rows


def plain(raw: bytes) -> str:
    s = raw.decode("utf-8", errors="replace")
    s = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", s)
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    return SPACE_RE.sub(" ", s)


def explicit_symbol_title(raw: bytes, ticker: str):
    text = plain(raw)
    ticker_re = re.compile(r"(?<![A-Z0-9.])" + re.escape(ticker) + r"(?![A-Z0-9.])", re.I)
    matches = list(ticker_re.finditer(text))
    for m in matches:
        lo, hi = max(0, m.start() - 900), min(len(text), m.end() + 900)
        window = text[lo:hi]
        commons = list(COMMON_RE.finditer(window))
        for cm in commons:
            around = window[max(0, cm.start()-120):min(len(window), cm.end()+120)]
            if not BAD_RE.search(around):
                return True, SPACE_RE.sub(" ", around).strip()[:500]
    # Inline-XBRL style fallback: both explicit DEI concepts in same filing.
    raw_text = raw.decode("utf-8", errors="replace")
    if re.search(r"(?is)(TradingSymbol|dei:TradingSymbol)[^>]*>\s*" + re.escape(ticker) + r"\s*<", raw_text):
        for m in re.finditer(r"(?is)(Security12bTitle|dei:Security12bTitle)[^>]*>(.*?)<", raw_text):
            val = SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(m.group(2)))).strip()
            if COMMON_RE.search(val) and not BAD_RE.search(val):
                return True, val[:500]
    return False, ""


def doc_url(cik10: str, accession: str, primary: str) -> str:
    c = str(int(cik10))
    a = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{c}/{a}/{primary}"


def main():
    gaps = list(csv.DictReader(GAPS.open(newline="", encoding="utf-8")))
    tickers = load_tickers()
    identity = load_identity()
    secmap = current_sec_map()
    cache = {}
    evidence = []
    unresolved = []

    for idx, g in enumerate(gaps, 1):
        ticker = (g.get("ticker") or "").strip().upper()
        buy_date = (g.get("buy_date") or "").strip()
        row = tickers.get(ticker, {})
        causal_cik = causal_identity_cik(identity, ticker, buy_date)
        hint_cik = cik_hint_from_tickers(row)
        current_cik = secmap.get(ticker, "")
        candidates = []
        for source, cik in [("causal_symbol_cik", causal_cik), ("sharadar_secfilings_retrieval_hint", hint_cik), ("current_sec_ticker_retrieval_hint", current_cik)]:
            if cik and cik not in {c for _, c in candidates}:
                candidates.append((source, cik))

        resolved = False
        err = ""
        for cik_source, cik in candidates:
            try:
                if cik not in cache:
                    cache[cik] = filing_rows(cik)
                filings = cache[cik]
            except Exception as e:
                err = f"submissions:{type(e).__name__}:{e}"
                continue
            eligible = []
            for f in filings:
                form = str(f.get("form") or "")
                fd = str(f.get("filingDate") or "")
                acc = str(f.get("accessionNumber") or "")
                primary = str(f.get("primaryDocument") or "")
                if form in FORMS and fd and fd < buy_date and acc and primary:
                    eligible.append((fd, form, acc, primary))
            eligible.sort(reverse=True)
            for fd, form, acc, primary in eligible[:20]:
                url = doc_url(cik, acc, primary)
                try:
                    raw = get(url)
                except Exception as e:
                    err = f"document:{type(e).__name__}:{e}"
                    continue
                ok, snippet = explicit_symbol_title(raw, ticker)
                if ok:
                    evidence.append({
                        "ticker": ticker,
                        "buy_date": buy_date,
                        "cik": cik,
                        "cik_source": cik_source,
                        "filing_date": fd,
                        "form": form,
                        "accession": acc,
                        "primary_document": primary,
                        "evidence_strength": "explicit_symbol_plus_common_title",
                        "security_title_snippet": snippet,
                        "source_url": url,
                    })
                    resolved = True
                    break
            if resolved:
                break
        if not resolved:
            unresolved.append({
                "ticker": ticker,
                "buy_date": buy_date,
                "legacy_name": row.get("name", ""),
                "causal_cik": causal_cik,
                "secfilings_hint_cik": hint_cik,
                "current_sec_map_cik": current_cik,
                "candidate_cik_count": len(candidates),
                "last_error": err,
            })
        if idx % 10 == 0:
            print(f"processed {idx}/{len(gaps)} resolved={len(evidence)} unresolved={len(unresolved)}", flush=True)

    fields = ["ticker","buy_date","cik","cik_source","filing_date","form","accession","primary_document","evidence_strength","security_title_snippet","source_url"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(evidence)
    ufields = ["ticker","buy_date","legacy_name","causal_cik","secfilings_hint_cik","current_sec_map_cik","candidate_cik_count","last_error"]
    with UNRESOLVED.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ufields); w.writeheader(); w.writerows(unresolved)

    total = len(gaps)
    report = {
        "input_gap_rows": total,
        "resolved_rows": len(evidence),
        "unresolved_rows": len(unresolved),
        "resolved_pct": len(evidence) / total if total else None,
        "method": "Targeted SEC EDGAR submissions + historical primary filings. Current Sharadar secfilings/current SEC ticker maps are retrieval hints only; positive classification requires a filing dated strictly before the buy with the exact Orion ticker explicitly co-occurring with a common/ordinary equity security title. Existing causal SEC symbol->CIK evidence is preferred where available.",
        "forms": sorted(FORMS),
        "unknown_policy": "unresolved remains unknown/ineligible",
        "generated_at_utc": str(date.today()),
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
