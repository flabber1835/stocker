#!/usr/bin/env python3
"""Build the phase-1 Orion PIT-only input set from supplied Sharadar files.

Fail closed: only fields already treated as point-in-time facts are copied.
No adjusted/split-adjusted price fields and no TICKERS snapshot fields are emitted.
"""

from __future__ import annotations

import csv
import gzip
import io
import pathlib
import zipfile

ROOT = pathlib.Path(".")
OUT = pathlib.Path("PIT input data")
OUT.mkdir(parents=True, exist_ok=True)


def write_gz(path: pathlib.Path, header: list[str], rows):
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=1, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as txt:
                w = csv.writer(txt, lineterminator="\n")
                w.writerow(header)
                w.writerows(rows)


for year in range(1998, 2027):
    matches = sorted(ROOT.glob(f"SHARADAR_SEP_{year}.csv*.gz"))
    if not matches:
        raise SystemExit(f"missing SEP source for {year}")
    src = matches[0]

    def sep_rows(src=src):
        with gzip.open(src, "rt", newline="") as f:
            for row in csv.DictReader(f):
                yield [row["ticker"], row["date"], row["volume"], row["closeunadj"]]

    write_gz(
        OUT / f"SEP_{year}_PIT_ONLY.csv.gz",
        ["ticker", "date", "volume", "closeunadj"],
        sep_rows(),
    )

with zipfile.ZipFile(ROOT / "SHARADAR_ACTIONS.zip") as z:
    member = z.namelist()[0]

    def action_rows():
        with z.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                yield [row["date"], row["action"], row["ticker"], row["value"]]

    write_gz(
        OUT / "ACTIONS_PIT_ONLY.csv.gz",
        ["date", "action", "ticker", "value"],
        action_rows(),
    )

with zipfile.ZipFile(ROOT / "SHARADAR_SFP.zip") as z:
    member = z.namelist()[0]

    def sfp_rows():
        with z.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row["ticker"] in {"SPY", "BIL"}:
                    yield [row["ticker"], row["date"], row["volume"], row["closeunadj"]]

    write_gz(
        OUT / "SFP_SPY_BIL_PIT_ONLY.csv.gz",
        ["ticker", "date", "volume", "closeunadj"],
        sfp_rows(),
    )
