#!/usr/bin/env python3
"""Build Orion Phase-2 PIT-safe price representations from pinned Sharadar sources.

Closed-world contract:
- reads only the branch-pinned Sharadar SEP/ACTIONS/SFP files supplied to it;
- verifies every source byte stream against Phase-1 MANIFEST.csv;
- never emits Sharadar adjusted price levels (open/close/closeadj);
- emits only causal, scale-invariant derived representations;
- uses no TICKERS metadata and no external packages.

SEP output is annual and contains:
  ticker,date,raw_open,signal_open,signal_close,split_factor_step,
  effective_split_ratio,dividend_basis

SFP output for SPY/BIL contains:
  ticker,date,raw_open,raw_close,close_to_close_factor,
  prior_close_to_open_factor,open_to_close_factor
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import pathlib
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

SEP_HEADER = [
    "ticker",
    "date",
    "raw_open",
    "signal_open",
    "signal_close",
    "split_factor_step",
    "effective_split_ratio",
    "dividend_basis",
]
SFP_HEADER = [
    "ticker",
    "date",
    "raw_open",
    "raw_close",
    "close_to_close_factor",
    "prior_close_to_open_factor",
    "open_to_close_factor",
]

SEP_REQUIRED_SOURCE = {"ticker", "date", "open", "close", "closeunadj", "closeadj"}
ACTIONS_REQUIRED_SOURCE = {"date", "action", "ticker", "value"}
SFP_REQUIRED_SOURCE = {"ticker", "date", "open", "close", "closeunadj", "closeadj"}
SPLIT_KINDS = {"split", "adrratiosplit"}


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt(x: float | None) -> str:
    if x is None or not math.isfinite(x):
        return ""
    # 17 significant digits round-trips a binary64 and is deterministic.
    return format(x, ".17g")


def parse_pos(value: str) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def parse_nonneg(value: str) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def load_phase1_manifest(path: pathlib.Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"empty Phase-1 manifest: {path}")
    source_hashes: dict[str, str] = {}
    for row in rows:
        name = row["source_file"]
        digest = row["source_sha256"]
        old = source_hashes.get(name)
        if old is not None and old != digest:
            raise SystemExit(f"conflicting source hashes for {name}")
        source_hashes[name] = digest
    return source_hashes


def candidate_sep(source_dir: pathlib.Path, logical_name: str) -> list[pathlib.Path]:
    m = re.fullmatch(r"SHARADAR_SEP_(\d{4})\.csv(?:\(\d+\))?\.gz", logical_name)
    if not m:
        return []
    year = m.group(1)
    candidates = sorted(source_dir.glob(f"SHARADAR_SEP_{year}.csv*.gz"))
    return [p for p in candidates if p.is_file()]


def resolve_hashed(candidates: Iterable[pathlib.Path], logical_name: str, expected: str) -> pathlib.Path:
    candidates = list(candidates)
    if not candidates:
        raise SystemExit(f"missing source: {logical_name}")
    matches = [p for p in candidates if sha256_file(p) == expected]
    if not matches:
        observed = ", ".join(f"{p}={sha256_file(p)}" for p in candidates)
        raise SystemExit(f"source hash mismatch for {logical_name}; expected {expected}; observed {observed}")
    chosen = matches[0]
    print(f"source verified: {logical_name}: {chosen}")
    return chosen


def require_fields(fieldnames: list[str] | None, required: set[str], source: str) -> None:
    got = set(fieldnames or [])
    missing = sorted(required - got)
    if missing:
        raise SystemExit(f"{source} missing required columns: {missing}")


def single_csv_member(zf: zipfile.ZipFile, path: pathlib.Path) -> str:
    members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if len(members) != 1:
        raise SystemExit(f"{path} must contain exactly one CSV member; found {members}")
    return members[0]


@dataclass(frozen=True)
class ActionBundle:
    split_product: float | None
    dividend_total: float | None


def load_actions(path: pathlib.Path) -> dict[tuple[str, str], ActionBundle]:
    temp: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: {"splits": [], "dividends": []})
    with zipfile.ZipFile(path) as zf:
        member = single_csv_member(zf, path)
        with zf.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
            reader = csv.DictReader(text)
            require_fields(reader.fieldnames, ACTIONS_REQUIRED_SOURCE, f"{path}::{member}")
            for row in reader:
                key = ((row.get("date") or "").strip(), (row.get("ticker") or "").strip())
                action = (row.get("action") or "").strip().lower()
                value = parse_nonneg(row.get("value") or "")
                if action in SPLIT_KINDS and value is not None and value > 0:
                    temp[key]["splits"].append(value)
                elif action == "dividend" and value is not None:
                    temp[key]["dividends"].append(value)
    out: dict[tuple[str, str], ActionBundle] = {}
    for key, values in temp.items():
        split_product = math.prod(values["splits"]) if values["splits"] else None
        dividend_total = sum(values["dividends"]) if values["dividends"] else None
        out[key] = ActionBundle(split_product, dividend_total)
    return out


def write_gzip_csv(path: pathlib.Path, header: list[str]):
    raw = path.open("wb")
    gz = gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=1, mtime=0)
    text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    return raw, gz, text, writer


def infer_dividend_basis(
    prev_raw: float,
    cur_raw: float,
    prev_adj: float,
    cur_adj: float,
    split_ratio: float,
    dividend: float,
) -> str:
    obs = cur_adj / prev_adj
    pre = (split_ratio * cur_raw + dividend) / prev_raw
    post = (split_ratio * cur_raw + split_ratio * dividend) / prev_raw
    epre = abs(math.log(max(pre, 1e-300) / max(obs, 1e-300)))
    epost = abs(math.log(max(post, 1e-300) / max(obs, 1e-300)))
    return "pre_split" if epre <= epost else "post_split"


def build_sep(
    source_dir: pathlib.Path,
    output_dir: pathlib.Path,
    source_hashes: dict[str, str],
    actions: dict[tuple[str, str], ActionBundle],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    base_factor: dict[str, float] = {}
    prev_factor: dict[str, float] = {}
    prev_raw: dict[str, float] = {}
    prev_adj: dict[str, float] = {}
    prev_date: dict[str, str] = {}

    manifest_rows: list[dict[str, object]] = []
    total_rows = 0
    split_action_rows = 0
    split_mismatch_gt_5pct = 0
    split_unverifiable = 0
    split_dividend_rows = 0

    # logical source names are taken from the authoritative Phase-1 manifest.
    by_year: dict[int, tuple[str, str]] = {}
    for logical, digest in source_hashes.items():
        m = re.fullmatch(r"SHARADAR_SEP_(\d{4})\.csv(?:\(\d+\))?\.gz", logical)
        if m:
            by_year[int(m.group(1))] = (logical, digest)

    for year in range(1998, 2027):
        if year not in by_year:
            raise SystemExit(f"Phase-1 manifest lacks SEP source for {year}")
        logical, expected = by_year[year]
        source = resolve_hashed(candidate_sep(source_dir, logical), logical, expected)
        output = output_dir / f"SEP_PRICE_{year}_PIT_ONLY.csv.gz"
        raw_out, gz_out, text_out, writer = write_gzip_csv(output, SEP_HEADER)
        rows = 0
        try:
            with gzip.open(source, "rt", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                require_fields(reader.fieldnames, SEP_REQUIRED_SOURCE, str(source))
                for row in reader:
                    ticker = (row.get("ticker") or "").strip()
                    date = (row.get("date") or "").strip()
                    if not ticker or not date:
                        raise SystemExit(f"missing ticker/date in {source}")
                    prior_date = prev_date.get(ticker)
                    if prior_date is not None and date < prior_date:
                        raise SystemExit(f"non-monotonic SEP dates for {ticker}: {date} < {prior_date}")

                    o = parse_pos(row.get("open") or "")
                    c = parse_pos(row.get("close") or "")
                    raw_close = parse_pos(row.get("closeunadj") or "")
                    adj = parse_pos(row.get("closeadj") or "")

                    raw_open = None
                    signal_open = None
                    signal_close = None
                    step = None
                    effective = None
                    dividend_basis = ""

                    factor = None
                    if c is not None and raw_close is not None:
                        factor = c / raw_close
                        if not math.isfinite(factor) or factor <= 0:
                            factor = None

                    if factor is not None:
                        if ticker not in base_factor:
                            base_factor[ticker] = factor
                        pf = prev_factor.get(ticker)
                        if pf is not None and pf > 0:
                            step = factor / pf
                            if not math.isfinite(step) or step <= 0:
                                raise SystemExit(f"invalid split factor step {ticker} {date}: {step}")
                        else:
                            step = 1.0

                        causal_scale = factor / base_factor[ticker]
                        if o is not None and c is not None and raw_close is not None:
                            raw_open = o * raw_close / c
                            signal_open = raw_open * causal_scale
                        if raw_close is not None:
                            signal_close = raw_close * causal_scale

                        # Strong equivalence invariant: causal coordinates must equal
                        # legacy split-adjusted levels up to one ticker-constant scale.
                        if signal_close is not None:
                            expected_signal_close = c / base_factor[ticker]
                            if not math.isclose(signal_close, expected_signal_close, rel_tol=2e-12, abs_tol=2e-12):
                                raise SystemExit(f"signal-close parity failure {ticker} {date}")
                        if signal_open is not None and o is not None:
                            expected_signal_open = o / base_factor[ticker]
                            if not math.isclose(signal_open, expected_signal_open, rel_tol=2e-12, abs_tol=2e-12):
                                raise SystemExit(f"signal-open parity failure {ticker} {date}")

                    bundle = actions.get((date, ticker))
                    if bundle and bundle.split_product is not None:
                        split_action_rows += 1
                        if step is None:
                            split_unverifiable += 1
                        else:
                            relerr = abs(step / bundle.split_product - 1.0)
                            if relerr > 0.05:
                                effective = step
                                split_mismatch_gt_5pct += 1
                            else:
                                effective = bundle.split_product

                    if bundle and bundle.split_product is not None and bundle.dividend_total is not None:
                        split_dividend_rows += 1
                        pr = prev_raw.get(ticker)
                        pa = prev_adj.get(ticker)
                        if (
                            pr is None
                            or raw_close is None
                            or pa is None
                            or adj is None
                            or effective is None
                            or effective <= 0
                        ):
                            raise SystemExit(f"cannot infer split/dividend basis for {ticker} {date}")
                        dividend_basis = infer_dividend_basis(
                            pr, raw_close, pa, adj, effective, bundle.dividend_total
                        )

                    writer.writerow([
                        ticker,
                        date,
                        fmt(raw_open),
                        fmt(signal_open),
                        fmt(signal_close),
                        fmt(step),
                        fmt(effective),
                        dividend_basis,
                    ])
                    rows += 1
                    total_rows += 1

                    if factor is not None:
                        prev_factor[ticker] = factor
                    if raw_close is not None:
                        prev_raw[ticker] = raw_close
                    if adj is not None:
                        prev_adj[ticker] = adj
                    prev_date[ticker] = date
        finally:
            text_out.flush()
            text_out.close()
            # TextIOWrapper closes GzipFile, which closes compression state but not
            # the underlying raw handle when fileobj is supplied.
            if not raw_out.closed:
                raw_out.close()

        manifest_rows.append({
            "file": output.name,
            "dataset": "SEP",
            "year": year,
            "rows": rows,
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
            "columns": "|".join(SEP_HEADER),
            "source_file": source.name,
            "source_sha256": expected,
        })
        print(f"built {output.name}: rows={rows:,} bytes={output.stat().st_size:,}")

    audit = {
        "sep_rows": total_rows,
        "split_action_rows": split_action_rows,
        "split_mismatch_gt_5pct": split_mismatch_gt_5pct,
        "split_unverifiable": split_unverifiable,
        "split_dividend_rows": split_dividend_rows,
        "ticker_count_with_price_factor": len(base_factor),
    }
    return manifest_rows, audit


def build_sfp(
    source: pathlib.Path,
    output_dir: pathlib.Path,
    expected_sha: str,
) -> tuple[dict[str, object], dict[str, object]]:
    actual = sha256_file(source)
    if actual != expected_sha:
        raise SystemExit(f"SFP source hash mismatch: {actual} != {expected_sha}")
    print(f"source verified: SHARADAR_SFP.zip: {source}")

    output = output_dir / "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"
    raw_out, gz_out, text_out, writer = write_gzip_csv(output, SFP_HEADER)
    prev_adj_close: dict[str, float] = {}
    prev_date: dict[str, str] = {}
    rows = 0
    by_ticker = defaultdict(int)
    try:
        with zipfile.ZipFile(source) as zf:
            member = single_csv_member(zf, source)
            with zf.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
                reader = csv.DictReader(text)
                require_fields(reader.fieldnames, SFP_REQUIRED_SOURCE, f"{source}::{member}")
                for row in reader:
                    ticker = (row.get("ticker") or "").strip()
                    if ticker not in {"SPY", "BIL"}:
                        continue
                    date = (row.get("date") or "").strip()
                    old_date = prev_date.get(ticker)
                    if old_date is not None and date < old_date:
                        raise SystemExit(f"non-monotonic SFP dates for {ticker}: {date} < {old_date}")

                    o = parse_pos(row.get("open") or "")
                    c = parse_pos(row.get("close") or "")
                    raw_close = parse_pos(row.get("closeunadj") or "")
                    adj_close = parse_pos(row.get("closeadj") or "")

                    raw_open = None
                    adjusted_open = None
                    if o is not None and c is not None and raw_close is not None:
                        raw_open = o * raw_close / c
                    if o is not None and c is not None and adj_close is not None:
                        adjusted_open = o * adj_close / c

                    c2c = None
                    pco = None
                    o2c = None
                    prev_adj = prev_adj_close.get(ticker)
                    if adj_close is not None and prev_adj is not None:
                        c2c = adj_close / prev_adj
                    if adjusted_open is not None and prev_adj is not None:
                        pco = adjusted_open / prev_adj
                    if adj_close is not None and adjusted_open is not None:
                        o2c = adj_close / adjusted_open

                    if c2c is not None and pco is not None and o2c is not None:
                        if not math.isclose(c2c, pco * o2c, rel_tol=2e-12, abs_tol=2e-12):
                            raise SystemExit(f"SFP factor identity failure {ticker} {date}")

                    writer.writerow([
                        ticker,
                        date,
                        fmt(raw_open),
                        fmt(raw_close),
                        fmt(c2c),
                        fmt(pco),
                        fmt(o2c),
                    ])
                    rows += 1
                    by_ticker[ticker] += 1
                    if adj_close is not None:
                        prev_adj_close[ticker] = adj_close
                    prev_date[ticker] = date
    finally:
        text_out.flush()
        text_out.close()
        if not raw_out.closed:
            raw_out.close()

    manifest = {
        "file": output.name,
        "dataset": "SFP",
        "year": "",
        "rows": rows,
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "columns": "|".join(SFP_HEADER),
        "source_file": "SHARADAR_SFP.zip",
        "source_sha256": expected_sha,
    }
    audit = {"sfp_rows": rows, "sfp_rows_by_ticker": dict(sorted(by_ticker.items()))}
    print(f"built {output.name}: rows={rows:,} bytes={output.stat().st_size:,}")
    return manifest, audit


def write_manifest(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    fields = ["file", "dataset", "year", "rows", "bytes", "sha256", "columns", "source_file", "source_sha256"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def validate_outputs(output_dir: pathlib.Path, manifest_rows: list[dict[str, object]]) -> None:
    expected = {row["file"] for row in manifest_rows}
    actual = {p.name for p in output_dir.glob("*.csv.gz")}
    if actual != expected:
        raise SystemExit(f"output set mismatch; missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    if len(expected) != 30:
        raise SystemExit(f"expected 30 Phase-2 price files, got {len(expected)}")

    allowed = {
        **{f"SEP_PRICE_{y}_PIT_ONLY.csv.gz": SEP_HEADER for y in range(1998, 2027)},
        "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz": SFP_HEADER,
    }
    for row in manifest_rows:
        name = str(row["file"])
        p = output_dir / name
        if sha256_file(p) != row["sha256"]:
            raise SystemExit(f"post-build hash drift: {name}")
        with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
            header = next(csv.reader(f))
        if header != allowed[name]:
            raise SystemExit(f"unexpected header in {name}: {header}")
        forbidden_exact = {"open", "close", "closeadj", "high", "low", "lastupdated"}
        leaked = forbidden_exact.intersection(header)
        if leaked:
            raise SystemExit(f"raw/hindsight-adjusted fields leaked into {name}: {sorted(leaked)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=pathlib.Path, required=True)
    ap.add_argument("--sfp", type=pathlib.Path, required=True)
    ap.add_argument("--phase1-manifest", type=pathlib.Path, required=True)
    ap.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = ap.parse_args()

    source_dir = args.source_dir.resolve()
    sfp = args.sfp.resolve()
    manifest = args.phase1_manifest.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for p in output_dir.iterdir():
        if p.is_file():
            p.unlink()
        else:
            raise SystemExit(f"unexpected directory in Phase-2 output: {p}")

    source_hashes = load_phase1_manifest(manifest)
    actions_expected = source_hashes.get("SHARADAR_ACTIONS.zip")
    sfp_expected = source_hashes.get("SHARADAR_SFP.zip")
    if not actions_expected or not sfp_expected:
        raise SystemExit("Phase-1 manifest lacks ACTIONS or SFP source hash")

    actions_path = resolve_hashed([source_dir / "SHARADAR_ACTIONS.zip"], "SHARADAR_ACTIONS.zip", actions_expected)
    actions = load_actions(actions_path)

    sep_manifest, sep_audit = build_sep(source_dir, output_dir, source_hashes, actions)
    sfp_manifest, sfp_audit = build_sfp(sfp, output_dir, sfp_expected)
    manifest_rows = sep_manifest + [sfp_manifest]
    validate_outputs(output_dir, manifest_rows)

    manifest_path = output_dir / "PRICE_RECONSTRUCTION_MANIFEST.csv"
    write_manifest(manifest_path, manifest_rows)
    audit = {
        "schema_version": 1,
        "contract": "Orion Phase-2 PIT-safe price reconstruction",
        "sep_output_columns": SEP_HEADER,
        "sfp_output_columns": SFP_HEADER,
        "forbidden_source_levels_not_emitted": ["SEP.open", "SEP.close", "SEP.closeadj", "SFP.open", "SFP.close", "SFP.closeadj"],
        "sep": sep_audit,
        "sfp": sfp_audit,
        "output_file_count": len(manifest_rows),
    }
    audit_path = output_dir / "PRICE_RECONSTRUCTION_AUDIT.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))
    print("Phase-2 price reconstruction PASS")


if __name__ == "__main__":
    main()
