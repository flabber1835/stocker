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
REVIEWED_LABEL = "RECONSTRUCTED_PATH_NOT_YET_CERTIFIED"
LEDGER_SHA256 = "1391630785c56daa2c4665abe792dd7b06d3697b47e2224edd380737fef133ab"
SUMMARY_SHA256 = "c483ccb077014eacdb742d3a74dcbce9fd68c41b0f77cc0ebbd6f6b64549cdf6"
REVIEWED_LEDGER_SHA256 = "3440fd1007062644868fbab5a872b52e87b9892f05673f825d27a385833143b6"
SCENARIOS = ("conflicts_excluded", "conflicts_common", "reviewed_18")
DEFAULT_LEDGER = ROOT / "backtester/data/champion-best-effort-security-types-v1.csv"
DEFAULT_SUMMARY = ROOT / "backtester/data/champion-best-effort-security-types-v1-summary.json"
DEFAULT_REVIEWED_LEDGER = ROOT / "backtester/data/champion-reviewed-security-types-v1.csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SecurityTypeEstimate:
    def __init__(self, ledger: Path, scenario: str, reviewed_ledger: Path = DEFAULT_REVIEWED_LEDGER):
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
        self.reviewed = {}
        if scenario == "reviewed_18":
            if _sha256(reviewed_ledger) != REVIEWED_LEDGER_SHA256:
                raise RuntimeError("reviewed security-type ledger hash mismatch")
            with reviewed_ledger.open(encoding="utf-8", newline="") as handle:
                reviewed_rows = list(csv.DictReader(handle))
            self.reviewed = {str(row["security_id"]): row for row in reviewed_rows}
            if len(self.reviewed) != 18 or len(reviewed_rows) != 18:
                raise RuntimeError("reviewed ledger must contain 18 unique security IDs")
            if {row["classification"] for row in reviewed_rows} != {"common", "non_common"}:
                raise RuntimeError("reviewed ledger must contain common and non-common decisions")
            base_conflicts = {sid for sid, row in self.rows.items() if row["classification"] == "unknown"}
            if set(self.reviewed) != base_conflicts:
                raise RuntimeError("reviewed ledger does not exactly cover the 18 base conflicts")
        self.calls = {"common": 0, "non_common": 0, "conflict_common": 0}

    def _classify(self, security_id: str, session: str, *, count: bool) -> str:
        sid = str(security_id)
        try:
            row = self.rows[sid]
        except KeyError as exc:
            raise RuntimeError(f"unknown canonical candidate absent from estimate ledger: {sid}") from exc
        if not (str(row["unknown_first_session"]) <= str(session) <= str(row["unknown_last_session"])):
            raise RuntimeError(f"estimate requested outside admitted interval: {sid} {session}")
        value = str(row["classification"])
        if value in {"common", "non_common"}:
            if count:
                self.calls[value] += 1
            return value
        if value == "unknown" and self.scenario == "reviewed_18":
            reviewed = self.reviewed[sid]
            if not (
                str(reviewed["unknown_first_session"]) <= str(session)
                <= str(reviewed["unknown_last_session"])
            ):
                raise RuntimeError(f"reviewed classification requested outside admitted interval: {sid} {session}")
            result = str(reviewed["classification"])
            if count:
                self.calls[result] += 1
            return result
        if value == "unknown" and self.scenario == "conflicts_common":
            if not str(row["disposition"]).startswith("REJECTED_"):
                raise RuntimeError(f"non-rejected unknown estimate row: {sid}")
            self.calls["conflict_common"] += 1
            return "common"
        if value == "unknown":
            return "unknown"
        raise RuntimeError(f"invalid estimate classification for {sid}: {value}")

    def classify(self, security_id: str, session: str) -> str:
        return self._classify(security_id, session, count=True)

    def peek(self, security_id: str, session: str) -> str:
        return self._classify(security_id, session, count=False)

    def summary(self) -> dict:
        return {
            "label": REVIEWED_LABEL if self.scenario == "reviewed_18" else LABEL,
            "scenario": self.scenario,
            "ledger_sha256": LEDGER_SHA256,
            "calls": dict(self.calls),
            "certification_eligible": False,
            "reviewed_ledger_sha256": REVIEWED_LEDGER_SHA256 if self.scenario == "reviewed_18" else None,
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
        anchor + "\n    _BEST_TYPES=_bestclass.SecurityTypeEstimate(Path(os.environ['BEST_EFFORT_SECURITY_TYPES']),os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO'])\n    def _BEST_PATH_CLASS(_tid,_session):\n        _mr=_metadata(int(_tid),_session); _value='' if _mr is None else str(_mr.get('security_type','')).strip().lower()\n        return _value if _value in ('common','non_common') else _BEST_TYPES.peek(str(sid[int(_tid)]),_session)",
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
        "metadata_fn=_metadata,\n                base_elig=",
        "metadata_fn=_metadata,classification_fn=_BEST_PATH_CLASS,\n                base_elig=",
        "effective path classification telemetry",
    )
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


def _write_reviewed_frontier(output: Path) -> None:
    with DEFAULT_REVIEWED_LEDGER.open(encoding="utf-8", newline="") as handle:
        authority = {row["security_id"]: row for row in csv.DictReader(handle)}
    with (output / "strategy-path-worklist.csv").open(encoding="utf-8", newline="") as handle:
        path = {row["security_id"]: row for row in csv.DictReader(handle)}
    fields = [
        "security_id", "ticker", "classification", "review_disposition",
        "base_candidate_sessions", "eligible_sessions", "momentum_pool_sessions",
        "durable_ranked_sessions", "recent_leadership_sessions", "pending_sessions",
        "held_sessions", "terminal_sessions", "incomplete_terminal_sessions",
        "best_durable_rank", "decision_role", "evidence_date", "evidence_kind", "evidence_url",
    ]
    rows = []
    for sid, evidence in sorted(authority.items(), key=lambda item: item[1]["ticker"]):
        observed = path.get(sid, {})
        numeric = lambda key: int(observed.get(key) or 0)
        if any(numeric(key) for key in ("durable_ranked_sessions", "recent_leadership_sessions", "pending_sessions", "held_sessions")):
            role = "ECONOMIC_PATH_CONTACT"
        elif numeric("eligible_sessions") or numeric("momentum_pool_sessions"):
            role = "RANKING_INPUT"
        elif numeric("base_candidate_sessions"):
            role = "BASE_CANDIDATE_ONLY"
        else:
            role = "NO_REPLAY_CONTACT"
        rows.append({key: evidence.get(key, observed.get(key, "")) for key in fields} | {
            "decision_role": role,
            **{key: numeric(key) for key in (
                "base_candidate_sessions", "eligible_sessions", "momentum_pool_sessions",
                "durable_ranked_sessions", "recent_leadership_sessions", "pending_sessions",
                "held_sessions", "terminal_sessions", "incomplete_terminal_sessions",
            )},
            "best_durable_rank": observed.get("best_durable_rank", ""),
        })
    with (output / "reviewed-security-decision-frontier.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    counts = {role: sum(row["decision_role"] == role for row in rows) for role in (
        "ECONOMIC_PATH_CONTACT", "RANKING_INPUT", "BASE_CANDIDATE_ONLY", "NO_REPLAY_CONTACT"
    )}
    (output / "reviewed-security-decision-frontier.json").write_text(
        json.dumps({"schema": "backtester.champion-reviewed-security-decision-frontier/1", "counts": counts, "rows": rows}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rewrite_outputs(output: Path, scenario: str) -> None:
    import pandas as pd

    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    result_label = REVIEWED_LABEL if scenario == "reviewed_18" else LABEL
    summary.update(
        status=result_label,
        certification_status="NOT_CERTIFIED",
        mode="champion_best_effort_security_type_sensitivity",
        classification_scenario=scenario,
        security_type_estimate_summary_sha256=SUMMARY_SHA256,
        reviewed_security_type_ledger_sha256=REVIEWED_LEDGER_SHA256 if scenario == "reviewed_18" else None,
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    identity_path = output / "pit-closure-replay-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.update(
        status=result_label,
        certification_status="NOT_CERTIFIED",
        classification_scenario=scenario,
        security_type_estimate_ledger_sha256=LEDGER_SHA256,
        security_type_estimate_summary_sha256=SUMMARY_SHA256,
        reviewed_security_type_ledger_sha256=REVIEWED_LEDGER_SHA256 if scenario == "reviewed_18" else None,
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
    if scenario == "reviewed_18":
        _write_reviewed_frontier(output)
    lines = [
        "# Champion reconstructed common-stock path — NOT YET PIT certified" if scenario == "reviewed_18" else "# Champion common-stock estimate — NOT PIT certified", "",
        f"Classification scenario: `{scenario}`", "",
        "| Window | Series | CAGR | Maximum drawdown | Ending multiple |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in rows.itertuples():
        lines.append(f"| {row.window_years} | {row.variant} | {float(row.cagr):.2%} | {float(row.max_drawdown):.2%} | {float(row.ending_multiple):.3f}x |")
    lines += ["", "The reviewed 18-name reconstruction is complete; path-level PIT certification remains pending." if scenario == "reviewed_18" else "These results use current-vendor classification inference and are not PIT certified."]
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
    print(f"[CLASSIFICATION REPLAY] {scenario} completed; NOT YET PIT certified", flush=True)
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
        label = REVIEWED_LABEL if args.scenario == "reviewed_18" else LABEL
        print(json.dumps({"status": "PASS", "label": label, "generated_source_sha256": hashlib.sha256(source.encode()).hexdigest()}))
        return 0
    return run(args.output, args.scenario, args.ledger)


if __name__ == "__main__":
    raise SystemExit(main())
