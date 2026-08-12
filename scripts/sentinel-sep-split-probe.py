#!/usr/bin/env python3
"""Can the pinned per-year SEP hashes be reproduced from the bulk ZIP?

## The question

`sentinel_1p1_standalone.py` pins a SHA256 for each per-year SEP file. Those
per-year files were produced by SPLITTING a bulk download — the bulk export is
one ~1 GB ZIP per table, and it was split so the pieces could be handed to a
tool with an upload limit.

If the split that produced the pinned files can be reproduced from the bulk ZIP
you still hold, then the pinned digests become verifiable again and the corpus
gets true byte-level provenance rather than row-level. gzip output depends on
compression level, on whether the original filename and an mtime are stamped
into the header, and on the implementation — so the space of plausible settings
is small enough to search exhaustively.

If nothing matches, that is also an answer: the per-year files came from
somewhere other than a plain split of this ZIP, and byte-level provenance is
genuinely unavailable.

## Why it probes ONE year

1998 is the smallest year and the pinned digest for it is as decisive as any
other: a setting that reproduces one year reproduces all of them, because the
same command made all 29. Probing one keeps this to seconds instead of an hour.

## Usage

```bash
python3 scripts/sentinel-sep-split-probe.py \
    --zip artifacts/sharadar-bulk/SHARADAR_SEP.zip
```

Pure stdlib. Writes nothing to disk — every candidate is built in memory.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STANDALONE = (REPO / "docs" / "sentinel-reference-implementation"
              / "sentinel_1p1_standalone.py")

PROBE_YEAR = 1998


def pinned_hash(year: int) -> str:
    src = STANDALONE.read_text()
    start = src.index("EXPECTED_HASHES = {")
    block = src[start:src.index("}", start)]
    found = dict(re.findall(r"'([^']+)'\s*:\s*'([0-9a-f]{64})'", block))
    name = f"SHARADAR_SEP_{year}.csv.gz"
    if name not in found:
        raise SystemExit(f"{name} is not pinned in {STANDALONE}")
    return found[name]


def extract_year(zip_path: Path, year: int):
    """Rows for one year, in file order, plus the header."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise SystemExit(f"expected one CSV, found {names}")
        with z.open(names[0]) as raw:
            text = io.TextIOWrapper(raw, "utf-8", newline="")
            header = text.readline()
            cols = next(csv.reader([header]))
            i_date = cols.index("date")
            prefix = f"{year}-"
            rows = []
            for line in text:
                parts = line.split(",")
                if len(parts) > i_date and parts[i_date].startswith(prefix):
                    rows.append(line if line.endswith("\n") else line + "\n")
    return header, rows


def candidates(header: str, rows: list):
    """Plausible ways that split could have been written."""
    body_lf = (header + "".join(rows)).encode()
    body_crlf = body_lf.replace(b"\n", b"\r\n")

    for label, payload in (("LF", body_lf), ("CRLF", body_crlf)):
        for level in range(1, 10):
            # mtime=0 and no embedded filename: the deterministic form.
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb",
                               compresslevel=level, mtime=0) as g:
                g.write(payload)
            yield f"{label} level={level} mtime=0 no-name", buf.getvalue()

            # With the filename stamped in, as `gzip file.csv` would do.
            buf = io.BytesIO()
            with gzip.GzipFile(filename=f"SHARADAR_SEP_{PROBE_YEAR}.csv",
                               fileobj=buf, mode="wb",
                               compresslevel=level, mtime=0) as g:
                g.write(payload)
            yield f"{label} level={level} mtime=0 with-name", buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--zip", dest="zip_path", type=Path, required=True)
    ap.add_argument("--year", type=int, default=PROBE_YEAR)
    args = ap.parse_args()

    want = pinned_hash(args.year)
    print(f"target  SHARADAR_SEP_{args.year}.csv.gz")
    print(f"pinned  {want}")
    print(f"reading {args.zip_path} ...", file=sys.stderr)

    header, rows = extract_year(args.zip_path, args.year)
    print(f"rows for {args.year}: {len(rows):,}")

    if not rows:
        print("\nNO ROWS for that year in this ZIP — wrong year or wrong file.")
        return 1

    hit = None
    tried = 0
    for label, blob in candidates(header, rows):
        tried += 1
        if hashlib.sha256(blob).hexdigest() == want:
            hit = label
            break

    print(f"\ncandidates tried: {tried}")
    if hit:
        print(f"\n  MATCH — the pinned split is reproducible from this ZIP")
        print(f"  settings: {hit}")
        print("\n  Byte-level provenance is available: re-split all 29 years")
        print("  with these settings and every pinned hash should verify.")
        return 0

    print("\n  NO MATCH.")
    print("  The per-year files were not produced by a plain gzip of this")
    print("  ZIP's rows under any common setting. Either the ZIP's contents")
    print("  have been restated since the split, or the split did something")
    print("  else — reordering, filtering, or a different writer.")
    print("\n  Byte-level provenance is unavailable. That is a finding, not a")
    print("  failure: certify forward against the corrected tape instead.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
