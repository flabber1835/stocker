#!/usr/bin/env python3
"""Split the bulk `SHARADAR_SEP.zip` into the per-year files the replay expects.

## Why this exists

Nasdaq's bulk export hands you one ZIP per TABLE. The reference implementation
reads one gzip per YEAR:

```text
bulk export        SHARADAR_SEP.zip                 ~1 GB, ~35M rows
standalone wants   SHARADAR_SEP_{1998..2026}.csv.gz  one per year
```

Same data, different packaging. The corpus inventory reports the per-year files
as "missing" because it checks names, and that reads as absent data when it is
actually a shape mismatch.

## What it does NOT do

It does not deduplicate, sort, filter, or repair. The replay applies
`drop_duplicates(['ticker','date'], keep='last')` itself, and doing it here
would move a documented behaviour of the strategy into an undocumented
behaviour of a data-prep script. Rows come out in the order they went in, with
the header preserved verbatim, and every column is carried through even though
the replay reads only seven of them.

## Why the output will NOT match the pinned SEP hashes

`sentinel_1p1_standalone.py` pins a SHA256 for each per-year file. Those digests
are of specific gzip ARTEFACTS, and gzip bytes depend on compression level,
implementation and the mtime stamped in the header — identical rows routinely
compress to different bytes. So a byte comparison against the pinned SEP hashes
would report a difference that does not exist in the data.

Provenance for SEP is therefore established on ROWS, not on file digests. This
script emits, per year:

```text
rows                  count of data rows written
first_date/last_date  the actual coverage, not the year label
distinct_tickers      population size
content_fingerprint   order-independent hash of the row set
```

The fingerprint sums per-row SHA256 digests modulo 2^256. Order-independent, so
it survives a different row ordering in the bulk export; duplicate-sensitive, so
a repeated row changes it — which XOR would not.

Output gzips are written with `mtime=0` so that re-running this script on the
same input reproduces the same bytes. That makes OUR artefacts comparable to
each other even though they cannot be compared to the pinned ones.

## Usage

```bash
python3 scripts/sentinel-split-sep-bulk.py \
    --zip artifacts/sharadar-bulk/SHARADAR_SEP.zip \
    --out artifacts/sharadar-bulk \
    --fingerprint sep-fingerprint.json
```

Pure stdlib, streaming, no network. Expect it to take a while: it decompresses
~1 GB and writes ~29 gzip files.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

#: The replay reads 1998 through its end year. Files must EXIST for every year
#: in that span — `standalone:342` raises FileNotFoundError rather than skipping
#: — so a year with no rows still gets a header-only file.
FIRST_YEAR = 1998
DEFAULT_LAST_YEAR = 2026

MODULUS = 1 << 256


class YearWriter:
    """One per-year gzip, plus its running fingerprint."""

    def __init__(self, path: Path, header: str):
        self.path = path
        # mtime=0: gzip stamps the current time by default, which would make
        # two runs over identical input produce different bytes.
        self.fh = gzip.GzipFile(filename=str(path), mode="wb", mtime=0)
        self.fh.write(header.encode())
        self.rows = 0
        self.first_date = None
        self.last_date = None
        self.tickers = set()
        self.fingerprint = 0

    def write(self, line: str, date: str, ticker: str):
        self.fh.write(line.encode())
        self.rows += 1
        if self.first_date is None or date < self.first_date:
            self.first_date = date
        if self.last_date is None or date > self.last_date:
            self.last_date = date
        self.tickers.add(ticker)
        digest = hashlib.sha256(line.encode()).digest()
        self.fingerprint = (self.fingerprint + int.from_bytes(digest, "big")) % MODULUS

    def close(self) -> dict:
        self.fh.close()
        return {
            "file": self.path.name,
            "rows": self.rows,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "distinct_tickers": len(self.tickers),
            "content_fingerprint": f"{self.fingerprint:064x}",
            "sha256_of_gzip": _sha256(self.path),
        }


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--zip", dest="zip_path", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True,
                    help="directory to write SHARADAR_SEP_{YYYY}.csv.gz into")
    ap.add_argument("--fingerprint", type=Path, default=Path("sep-fingerprint.json"))
    ap.add_argument("--last-year", type=int, default=DEFAULT_LAST_YEAR)
    ap.add_argument("--force", action="store_true",
                    help="overwrite per-year files that already exist")
    args = ap.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    years = list(range(FIRST_YEAR, args.last_year + 1))
    existing = [y for y in years if (out / f"SHARADAR_SEP_{y}.csv.gz").exists()]
    if existing and not args.force:
        raise SystemExit(
            f"{len(existing)} per-year files already exist in {out} "
            f"(first: SHARADAR_SEP_{existing[0]}.csv.gz). Pass --force to "
            f"overwrite, or point --out somewhere else. Refusing to write over "
            f"corpus files that another run may have produced.")

    with zipfile.ZipFile(args.zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise SystemExit(f"expected one CSV inside {args.zip_path}, found {names}")
        inner = names[0]
        print(f"reading {inner} from {args.zip_path}", file=sys.stderr)

        with z.open(inner) as raw:
            text = io.TextIOWrapper(raw, "utf-8", newline="")
            header = text.readline()
            if not header:
                raise SystemExit("empty CSV")
            cols = next(csv.reader([header]))
            try:
                i_date = cols.index("date")
                i_ticker = cols.index("ticker")
            except ValueError:
                raise SystemExit(f"no date/ticker column in header: {cols}")

            writers = {y: YearWriter(out / f"SHARADAR_SEP_{y}.csv.gz", header)
                       for y in years}
            skipped_years = {}
            malformed = 0
            total = 0

            for line in text:
                if not line.strip():
                    continue
                # Split cheaply: these rows have no embedded commas in the
                # fields we index. Fall back to the csv module if that fails.
                parts = line.rstrip("\n").split(",")
                if len(parts) <= max(i_date, i_ticker):
                    parts = next(csv.reader([line]))
                    if len(parts) <= max(i_date, i_ticker):
                        malformed += 1
                        continue
                date = parts[i_date]
                try:
                    year = int(date[:4])
                except ValueError:
                    malformed += 1
                    continue
                w = writers.get(year)
                if w is None:
                    skipped_years[year] = skipped_years.get(year, 0) + 1
                    continue
                w.write(line if line.endswith("\n") else line + "\n",
                        date, parts[i_ticker])
                total += 1
                if total % 5_000_000 == 0:
                    print(f"  {total:,} rows ...", file=sys.stderr)

    report = {
        "source_zip": str(args.zip_path),
        "source_zip_sha256": _sha256(args.zip_path),
        "inner_csv": inner,
        "columns": cols,
        "rows_written": total,
        "malformed_rows_skipped": malformed,
        "rows_outside_year_range": skipped_years,
        "years": {},
    }
    for y in years:
        report["years"][str(y)] = writers[y].close()

    args.fingerprint.write_text(json.dumps(report, indent=2, sort_keys=True))

    empty = [y for y in years if report["years"][str(y)]["rows"] == 0]
    print(f"\n  rows written        {total:,}")
    print(f"  malformed skipped   {malformed:,}")
    if skipped_years:
        print(f"  outside {FIRST_YEAR}-{args.last_year}: {skipped_years}")
    print(f"  per-year files      {len(years)}  ({FIRST_YEAR}..{args.last_year})")
    if empty:
        print(f"  EMPTY years         {empty}")
    print(f"  fingerprint written {args.fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
