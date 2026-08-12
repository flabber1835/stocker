#!/usr/bin/env python3
"""Step 1 of the raw-breadth certification: inventory and verify the corpus.

Run this on the machine that HAS the Sharadar corpus. It answers, with
evidence rather than filename convention:

```text
which of the 32 required inputs are present, and do their bytes match
which duplicates exist, and are they byte-identical or materially different
what date range each SEP year file actually covers
does SFP carry SPY and BIL, which the regime sensor and the sleeve need
```

## The manifest is READ, never transcribed

`docs/sentinel-reference-implementation/sentinel_1p1_standalone.py` pins a
SHA256 for each of the 32 inputs it consumes. This script parses that table out
of the source rather than restating it, for the same reason
`controller/frozen_rule.py` loads its thresholds instead of copying them: a
second copy is a second thing to drift.

Those hashes describe the corpus the recovered result was produced from. A
mismatch is not automatically an error — Sharadar restates history, so a newer
pull legitimately differs — but it IS the difference between "we reproduced the
tape" and "we reproduced something from a different corpus", and it must be
recorded before any reconstruction is run rather than discovered afterwards.

## Usage

```bash
python3 scripts/sentinel-corpus-inventory.py --sharadar /path/to/corpus \
    --out corpus-inventory.json
```

Pure stdlib. No pandas, no network, and it reads nothing but the corpus
directory and the standalone source. It writes one JSON file and prints a
summary; it modifies nothing.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STANDALONE = (REPO / "docs" / "sentinel-reference-implementation"
              / "sentinel_1p1_standalone.py")


def pinned_hashes(path: Path = STANDALONE) -> dict:
    """Parse EXPECTED_HASHES out of the reference implementation."""
    src = path.read_text()
    start = src.index("EXPECTED_HASHES = {")
    block = src[start:src.index("}", start)]
    found = re.findall(r"'([^']+)'\s*:\s*'([0-9a-f]{64})'", block)
    if not found:
        raise SystemExit(f"no pinned hashes parsed from {path}")
    return dict(found)


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sep_date_range(path: Path) -> dict:
    """First and last `date` in a SEP year file, plus a row count.

    Streamed, because these are hundreds of MB uncompressed. Reports the raw
    min/max seen rather than assuming the file is sorted.
    """
    lo = hi = None
    rows = 0
    tickers = set()
    try:
        with gzip.open(path, "rt", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "date" not in reader.fieldnames:
                return {"error": "no date column", "columns": reader.fieldnames}
            for row in reader:
                d = row.get("date")
                if not d:
                    continue
                rows += 1
                if lo is None or d < lo:
                    lo = d
                if hi is None or d > hi:
                    hi = d
                if len(tickers) < 200000:
                    tickers.add(row.get("ticker"))
    except Exception as exc:                       # noqa: BLE001 - reported
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"first_date": lo, "last_date": hi, "rows": rows,
            "distinct_tickers": len(tickers)}


def zip_csv_info(path: Path, want_tickers=None) -> dict:
    """Header and row count of the single CSV inside a Sharadar ZIP."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                return {"error": f"expected one CSV, found {names}"}
            info = {"inner_csv": names[0]}
            seen = defaultdict(int)
            rows = 0
            with z.open(names[0]) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, "utf-8",
                                                         newline=""))
                info["columns"] = reader.fieldnames
                for row in reader:
                    rows += 1
                    if want_tickers:
                        t = row.get("ticker")
                        if t in want_tickers:
                            seen[t] += 1
            info["rows"] = rows
            if want_tickers:
                info["wanted_ticker_rows"] = dict(seen)
                info["missing_wanted"] = sorted(set(want_tickers) - set(seen))
            return info
    except Exception as exc:                       # noqa: BLE001 - reported
        return {"error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sharadar", type=Path, required=True,
                    help="directory holding SEP_*.csv.gz and the three ZIPs")
    ap.add_argument("--out", type=Path, default=Path("corpus-inventory.json"))
    ap.add_argument("--deep", action="store_true",
                    help="also stream every SEP file for date coverage "
                         "(slow: reads the whole corpus)")
    args = ap.parse_args()

    root: Path = args.sharadar
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")

    want = pinned_hashes()
    report = {"corpus_dir": str(root.resolve()),
              "pinned_manifest_source": str(STANDALONE.relative_to(REPO)),
              "pinned_file_count": len(want),
              "files": {}, "duplicates_by_content": {},
              "summary": {}}

    # Every file in the directory, not only the expected ones: an unexpected
    # duplicate under a different name is exactly what step 1 is looking for.
    on_disk = sorted(p for p in root.iterdir() if p.is_file())
    by_hash = defaultdict(list)

    print(f"hashing {len(on_disk)} files in {root} ...", file=sys.stderr)
    for p in on_disk:
        digest = sha256(p)
        by_hash[digest].append(p.name)
        entry = {"size_bytes": p.stat().st_size, "sha256": digest}
        if p.name in want:
            entry["pinned"] = want[p.name]
            entry["matches_pinned"] = (digest == want[p.name])
        else:
            entry["pinned"] = None
            entry["matches_pinned"] = None
        report["files"][p.name] = entry

    for digest, names in by_hash.items():
        if len(names) > 1:
            report["duplicates_by_content"][digest] = sorted(names)

    missing = sorted(n for n in want if n not in report["files"])
    mismatched = sorted(n for n, e in report["files"].items()
                        if e["matches_pinned"] is False)
    matched = sorted(n for n, e in report["files"].items()
                     if e["matches_pinned"] is True)
    extra = sorted(n for n, e in report["files"].items()
                   if e["pinned"] is None)

    # The three ZIPs carry the metadata the reconstruction depends on. SFP is
    # NOT optional: load_spy_bil() reads SPY for the regime sensor and BIL for
    # the defensive sleeve, so its absence blocks the chain rather than
    # degrading it.
    for name, wanted in (("SHARADAR_TICKERS.zip", None),
                         ("SHARADAR_ACTIONS.zip", None),
                         ("SHARADAR_SFP.zip", {"SPY", "BIL"})):
        p = root / name
        if p.exists():
            report["files"][name]["content"] = zip_csv_info(p, wanted)

    if args.deep:
        for name in sorted(n for n in report["files"] if n.startswith("SHARADAR_SEP_")):
            print(f"  scanning {name} ...", file=sys.stderr)
            report["files"][name]["content"] = sep_date_range(root / name)

    # A bulk export packs each TABLE into one ZIP; the replay reads one gzip per
    # YEAR. When SHARADAR_SEP.zip is present and the per-year files are not,
    # the SEP rows are here in a different shape — reporting that as "missing"
    # reads as absent data, which is a materially different and much worse
    # finding than the true one.
    sep_missing = [n for n in missing if n.startswith("SHARADAR_SEP_")]
    bulk_sep_present = "SHARADAR_SEP.zip" in report["files"]
    unpackaged = bulk_sep_present and len(sep_missing) == len(missing)

    report["summary"] = {
        "pinned_total": len(want),
        "matched_pinned": len(matched),
        "mismatched_pinned": len(mismatched),
        "missing": len(missing),
        "unexpected_extra_files": len(extra),
        "duplicate_content_groups": len(report["duplicates_by_content"]),
        "missing_files": missing,
        "mismatched_files": mismatched,
        "extra_files": extra,
        "sep_present_only_as_bulk_zip": unpackaged,
        # Deliberately NOT a single pass/fail. The metadata inputs can be
        # byte-exact while SEP is merely unsplit, and those are different
        # states with different next steps.
        "metadata_inputs_byte_identical": all(
            report["files"].get(n, {}).get("matches_pinned") is True
            for n in ("SHARADAR_TICKERS.zip", "SHARADAR_ACTIONS.zip",
                      "SHARADAR_SFP.zip")),
        "sep_per_year_files_present": not sep_missing,
        "corpus_is_byte_identical_to_the_recovered_run":
            not missing and not mismatched,
    }

    args.out.write_text(json.dumps(report, indent=2, sort_keys=True))

    s = report["summary"]
    print(f"\n  pinned inputs required   {s['pinned_total']}")
    print(f"  byte-identical           {s['matched_pinned']}")
    print(f"  present but DIFFERENT    {s['mismatched_pinned']}")
    print(f"  missing                  {s['missing']}")
    print(f"  unexpected extra files   {s['unexpected_extra_files']}")
    print(f"  duplicate content groups {s['duplicate_content_groups']}")
    if mismatched:
        print("\n  DIFFERENT from the recovered run:")
        for n in mismatched:
            print(f"    {n}")
    if missing:
        print("\n  MISSING:")
        for n in missing:
            print(f"    {n}")
    for digest, names in report["duplicates_by_content"].items():
        print(f"\n  identical bytes under {len(names)} names: {', '.join(names)}")
    print(f"\n  metadata inputs byte-identical (TICKERS/ACTIONS/SFP): "
          f"{s['metadata_inputs_byte_identical']}")
    print(f"  SEP per-year files present:  {s['sep_per_year_files_present']}")
    if s["sep_present_only_as_bulk_zip"]:
        print("\n  SEP IS PRESENT AS A BULK ZIP, NOT AS PER-YEAR FILES.")
        print("  The rows are here in a different shape — this is packaging,")
        print("  not absent data. Split it before running any reconstruction:")
        print("    python3 scripts/sentinel-split-sep-bulk.py \\")
        print(f"        --zip {root}/SHARADAR_SEP.zip \\")
        print(f"        --out {root} --fingerprint sep-fingerprint.json")
        print("\n  Note: the split files will NOT match the pinned SEP hashes.")
        print("  Those digests are of specific gzip artefacts and gzip bytes")
        print("  vary with compression level, implementation and mtime. SEP")
        print("  provenance is established on ROWS — see the fingerprint file.")
    print(f"\n  written: {args.out}")
    print("  every pinned input byte-identical: "
          f"{s['corpus_is_byte_identical_to_the_recovered_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
