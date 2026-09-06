#!/usr/bin/env python3
"""Find dated Wayback corroboration for Champion security-type conflicts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LEDGER_SHA256 = "1391630785c56daa2c4665abe792dd7b06d3697b47e2224edd380737fef133ab"
USER_AGENT = "stocker-research-wayback/1.0 contact=repository:flabber1835/stocker"
DOMAINS = {
    "AB": ["alliancebernstein.com"],
    "BEP": ["brookfieldrenewable.com"],
    "BIP": ["bip.brookfield.com", "brookfield.com/infrastructure"],
    "BPY": ["bpy.brookfield.com", "brookfieldproperties.com"],
    "EMESQ": ["emergelp.com", "emergeenergyservices.com"],
    "EPD": ["enterpriseproducts.com"],
    "ETP": ["energytransfer.com", "energytransferpartners.com"],
    "LB": ["landbridgeco.com"],
    "MMP": ["magellanlp.com", "magellanmidstream.com"],
    "PCG": ["pcg.com"],
    "PDS": ["precisiondrilling.com"],
    "RTLR": ["rattlermidstream.com"],
    "SHLX": ["shellmidstreampartners.com"],
    "TFC": ["truist.com", "bbt.com"],
    "TRP": ["tcenergy.com", "transcanada.com"],
    "USAC": ["usacompression.com"],
    "WES": ["westernmidstream.com", "westernmidstream.com/investors"],
    "WPZ": ["williams.com", "williamslp.com"],
}
NON_COMMON = re.compile(r"\b(common units?|limited partner(?:ship)? interests?|partnership units?)\b", re.I)
COMMON = re.compile(r"\b(shares? of common stock|common shares?|ordinary shares?)\b", re.I)
TAGS = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get(url: str, attempts: int = 3) -> bytes:
    error = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=45) as response:
                return response.read()
        except Exception as exc:  # network evidence is recorded, never hidden
            error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {url}: {error}")


def cdx(domain: str, first: str, last: str, limit: int) -> list[dict]:
    params = {
        "url": domain + "/*",
        "from": first[:4], "to": last[:4], "output": "json",
        "fl": "timestamp,original,statuscode,mimetype,digest",
        "filter": ["statuscode:200", "mimetype:text/html", "original:.*(invest|stock|unit|share|securit|annual|faq).*"],
        "collapse": "digest", "limit": str(limit),
    }
    url = "https://web.archive.org/cdx/search/cdx?" + urlencode(params, doseq=True)
    payload = json.loads(get(url))
    if not payload:
        return []
    keys = payload[0]
    return [dict(zip(keys, values)) for values in payload[1:]]


def visible_text(raw: bytes) -> str:
    value = raw.decode("utf-8", "replace")
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
    return SPACE.sub(" ", html.unescape(TAGS.sub(" ", value))).strip()


def matches(text: str) -> tuple[str, str]:
    found_non = list(NON_COMMON.finditer(text))
    found_common = list(COMMON.finditer(text))
    if not found_non and not found_common:
        return "none", ""
    kinds = {"non_common" if match.re is NON_COMMON else "common" for match in found_non + found_common}
    implication = next(iter(kinds)) if len(kinds) == 1 else "conflict"
    match = sorted(found_non + found_common, key=lambda item: item.start())[0]
    start, end = max(0, match.start() - 160), min(len(text), match.end() + 160)
    return implication, text[start:end]


def run(ledger: Path, output: Path, captures_per_security: int) -> dict:
    if sha256(ledger) != LEDGER_SHA256:
        raise RuntimeError("Champion inference ledger hash mismatch")
    with ledger.open(encoding="utf-8", newline="") as handle:
        conflicts = [row for row in csv.DictReader(handle) if row["classification"] == "unknown"]
    if len(conflicts) != 18 or set(row["ticker"] for row in conflicts) != set(DOMAINS):
        raise RuntimeError("Wayback target set must equal the 18 rejected conflicts")

    evidence, status = [], {}
    for row in sorted(conflicts, key=lambda value: value["ticker"]):
        ticker = row["ticker"]
        candidates, errors = [], []
        for domain in DOMAINS[ticker]:
            try:
                candidates.extend(cdx(domain, row["unknown_first_session"], row["unknown_last_session"], 100))
            except Exception as exc:
                errors.append(str(exc))
            time.sleep(1)
        candidates.sort(key=lambda value: (value["timestamp"], value["original"]))
        # Spread inspection across the interval instead of taking only early captures.
        if len(candidates) > captures_per_security:
            indexes = {round(i * (len(candidates) - 1) / (captures_per_security - 1)) for i in range(captures_per_security)}
            candidates = [candidates[i] for i in sorted(indexes)]
        implications = set()
        for capture in candidates:
            replay = f"https://web.archive.org/web/{capture['timestamp']}id_/{capture['original']}"
            try:
                implication, snippet = matches(visible_text(get(replay)))
            except Exception as exc:
                errors.append(str(exc)); continue
            if implication == "none":
                continue
            implications.add(implication)
            evidence.append({
                "ticker": ticker, "security_id": row["security_id"],
                "unknown_first_session": row["unknown_first_session"],
                "unknown_last_session": row["unknown_last_session"],
                "capture_timestamp": capture["timestamp"], "original_url": capture["original"],
                "wayback_url": replay, "implication": implication, "matched_context": snippet,
            })
        resolved = "unresolved"
        if implications == {"common"}: resolved = "common"
        elif implications == {"non_common"}: resolved = "non_common"
        elif implications: resolved = "conflict"
        status[ticker] = {"result": resolved, "candidate_captures": len(candidates), "evidence_rows": sum(x["ticker"] == ticker for x in evidence), "errors": errors}

    output.mkdir(parents=True, exist_ok=True)
    columns = ["ticker", "security_id", "unknown_first_session", "unknown_last_session", "capture_timestamp", "original_url", "wayback_url", "implication", "matched_context"]
    with (output / "wayback-evidence.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n"); writer.writeheader(); writer.writerows(evidence)
    summary = {"schema": "backtester.champion-wayback-security-type-evidence/1", "target_count": 18, "ledger_sha256": LEDGER_SHA256, "status_by_ticker": status, "counts": {key: sum(value["result"] == key for value in status.values()) for key in ("common", "non_common", "conflict", "unresolved")}}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [output / "wayback-evidence.csv", output / "summary.json"]
    (output / "SHA256SUMS.txt").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in files), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=Path("backtester/data/champion-best-effort-security-types-v1.csv"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--captures-per-security", type=int, default=12)
    args = parser.parse_args()
    if args.captures_per_security < 2 or args.captures_per_security > 30:
        raise RuntimeError("captures-per-security must be in [2, 30]")
    run(args.ledger, args.output, args.captures_per_security)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
