#!/usr/bin/env python3
"""Run frozen Champion with the non-PIT security-type estimate overlay."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABEL = "BEST_EFFORT_NOT_PIT_CERTIFIED"
LEDGER_SHA256 = "1391630785c56daa2c4665abe792dd7b06d3697b47e2224edd380737fef133ab"
SUMMARY_SHA256 = "c483ccb077014eacdb742d3a74dcbce9fd68c41b0f77cc0ebbd6f6b64549cdf6"
SCENARIOS = ("conflicts_excluded", "conflicts_common")
DEFAULT_LEDGER = ROOT / "backtester/data/champion-best-effort-security-types-v1.csv"
DEFAULT_SUMMARY = ROOT / "backtester/data/champion-best-effort-security-types-v1-summary.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SecurityTypeEstimate:
    def __init__(self, ledger: Path, scenario: str):
        if scenario not in SCENARIOS:
            raise RuntimeError(f"unsupported classification scenario: {scenario}")
        if _sha256(ledger) != LEDGER_SHA256:
            raise RuntimeError("best-effort security-type ledger hash mismatch")
        self.scenario = scenario
        with ledger.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.rows = {str(row["security_id"]): row for row in rows}
        if len(self.rows) != len(rows) or len(rows) != 1751:
            raise RuntimeError("best-effort ledger must contain 1,751 unique security IDs")
        self.calls = {"common": 0, "non_common": 0, "conflict_common": 0}

    def classify(self, security_id: str, session: str) -> str:
        sid = str(security_id)
        try:
            row = self.rows[sid]
        except KeyError as exc:
            raise RuntimeError(f"unknown canonical candidate absent from estimate ledger: {sid}") from exc
        if not (str(row["unknown_first_session"]) <= str(session) <= str(row["unknown_last_session"])):
            raise RuntimeError(f"estimate requested outside admitted interval: {sid} {session}")
        value = str(row["classification"])
        if value in {"common", "non_common"}:
            self.calls[value] += 1
            return value
        if value == "unknown" and self.scenario == "conflicts_common":
            if not str(row["disposition"]).startswith("REJECTED_"):
                raise RuntimeError(f"non-rejected unknown estimate row: {sid}")
            self.calls["conflict_common"] += 1
            return "common"
        if value == "unknown":
            return "unknown"
        raise RuntimeError(f"invalid estimate classification for {sid}: {value}")

    def summary(self) -> dict:
        return {
            "label": LABEL,
            "scenario": self.scenario,
            "ledger_sha256": LEDGER_SHA256,
            "calls": dict(self.calls),
            "certification_eligible": False,
        }


def _once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def install(text: str) -> str:
    text = _once(
        text,
        "from collections import defaultdict\n",
        "from collections import defaultdict\nfrom backtester import research_champion_best_effort_classification as _bestclass\n",
        "overlay import",
    )
    anchor = "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    text = _once(
        text,
        anchor,
        anchor + "\n    _BEST_TYPES=_bestclass.SecurityTypeEstimate(Path(os.environ['BEST_EFFORT_SECURITY_TYPES']),os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO'])",
        "overlay initialization",
    )
    old = "            elig=_sec_ok&_base_elig"
    new = """            for _j in np.flatnonzero(_base_elig):
                _tid=int(tids[int(_j)]); _mr=_metadata(_tid,ds)
                if _mr is None or str(_mr.get('security_type','')).strip().lower()=='unknown':
                    _estimated=_BEST_TYPES.classify(str(sid[_tid]),ds)
                    _sec_ok[int(_j)]=_estimated=='common'
            elig=_sec_ok&_base_elig"""
    text = _once(text, old, new, "candidate classification overlay")
    text = _once(
        text,
        "'strict_candidate_security_type_unknown_breakdown':_UNKNOWN_DETAIL,",
        "'strict_candidate_security_type_unknown_breakdown':_UNKNOWN_DETAIL,\n        'best_effort_security_type_overlay':_BEST_TYPES.summary(),",
        "overlay summary",
    )
    compile(text, "<Champion-best-effort-classification>", "exec")
    return text


def build_source(output: Path) -> str:
    from backtester import run_research_champion_pit_closure_20y as closure
    return install(closure.build_source(output))


def _rewrite_outputs(output: Path, scenario: str) -> None:
    import pandas as pd

    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        status=LABEL,
        certification_status="NOT_CERTIFIED",
        mode="champion_best_effort_security_type_sensitivity",
        classification_scenario=scenario,
        security_type_estimate_summary_sha256=SUMMARY_SHA256,
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    identity_path = output / "pit-closure-replay-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.update(
        status=LABEL,
        certification_status="NOT_CERTIFIED",
        classification_scenario=scenario,
        security_type_estimate_ledger_sha256=LEDGER_SHA256,
        security_type_estimate_summary_sha256=SUMMARY_SHA256,
    )
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for name in ("metrics.csv", "daily.csv.gz"):
        path = output / name
        frame = pd.read_csv(path)
        frame["certification_status"] = "NOT_CERTIFIED"
        frame["classification_scenario"] = scenario
        if name.endswith(".gz"):
            frame.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
        else:
            frame.to_csv(path, index=False)

    metrics = pd.read_csv(output / "metrics.csv")
    rows = metrics[metrics["window_years"].astype(str).isin(["5", "10", "15", "20", "max"])]
    lines = [
        "# Champion common-stock estimate — NOT PIT certified", "",
        f"Classification scenario: `{scenario}`", "",
        "| Window | Series | CAGR | Maximum drawdown | Ending multiple |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in rows.itertuples():
        lines.append(f"| {row.window_years} | {row.variant} | {float(row.cagr):.2%} | {float(row.max_drawdown):.2%} | {float(row.ending_multiple):.3f}x |")
    lines += ["", "These results use current-vendor classification inference and are not PIT certified."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    evidence = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt")
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in evidence), encoding="utf-8"
    )


def run(output: Path, scenario: str, ledger: Path = DEFAULT_LEDGER) -> int:
    from backtester import run_research_champion_pit_closure_20y as closure

    if os.environ.get("PIT_OFFICIAL_BACKTEST", "0") not in ("", "0"):
        raise RuntimeError("best-effort classification replay requires PIT_OFFICIAL_BACKTEST=0")
    if _sha256(DEFAULT_SUMMARY) != SUMMARY_SHA256:
        raise RuntimeError("best-effort classification summary hash mismatch")
    original = closure.build_source
    closure.build_source = lambda destination: install(original(destination))
    os.environ["BEST_EFFORT_SECURITY_TYPES"] = str(ledger.resolve())
    os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"] = scenario
    try:
        rc = closure.run(output)
    finally:
        closure.build_source = original
    if rc:
        return rc
    _rewrite_outputs(output.resolve(), scenario)
    print(f"[BEST EFFORT CLASSIFICATION] {scenario} completed; NOT PIT certified", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        os.environ["BEST_EFFORT_SECURITY_TYPES"] = str(args.ledger.resolve())
        os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"] = args.scenario
        source = build_source(args.output)
        print(json.dumps({"status": "PASS", "label": LABEL, "generated_source_sha256": hashlib.sha256(source.encode()).hexdigest()}))
        return 0
    return run(args.output, args.scenario, args.ledger)


if __name__ == "__main__":
    raise SystemExit(main())
