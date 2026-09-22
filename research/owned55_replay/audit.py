"""Independently audit a completed, segmented Owned55 replay."""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess


START = date.fromisoformat("2006-07-31")
END = "2026-07-31"


def rows(path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def run(root: Path):
    segments = sorted(path for path in root.glob("segment-*") if path.is_dir())
    assert [path.name for path in segments] == [f"segment-{n:03d}" for n in range(1, len(segments)+1)]
    assert segments and json.loads((segments[-1]/"comparison-status.json").read_text())["status"] == "COMPLETE"
    retained = subprocess.check_output(["git", "show", "7b5dda96ce4235363c5c6ded3974d3fb2970f432:audit/economic-replay-resume-430/accepted-daily.jsonl.gz"])
    baseline = [json.loads(line) for line in gzip.decompress(retained).splitlines()]
    all_daily, all_trace, bounds = [], [], []
    previous_packet = None
    for directory in segments:
        daily, trace = list(rows(directory/"daily.jsonl")), list(rows(directory/"comparison.jsonl"))
        assert daily and trace and len(daily) == len(trace)
        assert [x["date"] for x in daily] == [x["session"] for x in trace]
        pointer = json.loads((directory/"latest-checkpoint.json").read_text())
        raw = Path(pointer["path"]).read_bytes()
        assert len(raw) == pointer["bytes"] and hashlib.sha256(raw).hexdigest() == pointer["sha256"]
        packet = json.loads(gzip.decompress(raw))
        extra = packet["owned55_research"]
        assert extra["sha256"] == digest({key: value for key, value in extra.items() if key != "sha256"})
        assert packet["state"]["last_processed_session"] == pointer["last_session"] == trace[-1]["session"] == extra["cursor"]
        if previous_packet is not None:
            assert previous_packet["state"]["last_processed_session"] < trace[0]["session"]
            assert extra["binding"] == previous_packet["owned55_research"]["binding"]
        bounds.append(dict(segment=directory.name, first=trace[0]["session"], last=trace[-1]["session"],
                           rows=len(trace), checkpoint_sha256=pointer["sha256"]))
        previous_packet = packet
        all_daily.extend(daily)
        all_trace.extend(trace)
    assert len(all_daily) == len(baseline) == 5176
    assert all_daily[0]["date"] == baseline[0]["date"] == "2006-01-03"
    assert all_daily[-1]["date"] == baseline[-1]["date"] == END
    assert [x["date"] for x in all_daily] == [x["date"] for x in baseline]
    previous = None
    summary = {}
    for key in ("current", "owned55"):
        base = peak = previous_nav = None
        maximum_drawdown = Decimal(0)
        measured = 0
        events = []
        for daily, trace, original in zip(all_daily, all_trace, baseline, strict=True):
            day = daily["date"]
            economic = trace[key+"_economics"]
            nav = Decimal(economic["strategy_nav"])
            assert economic["last_session"] == day
            if previous_nav is not None:
                assert Decimal(economic["previous_strategy_nav"]) == previous_nav
                # Independent chained daily account identity.
                assert abs(nav - previous_nav * Decimal(economic["net_factor"])) < Decimal("1e-16")
                assert Decimal(economic["held_allocation"]) == Decimal(previous[key+"_economics"]["pending_allocation"])
            previous_nav = nav
            if key == "current":
                assert nav == Decimal(daily["nav"]) == Decimal(original["nav"])
                assert trace["current"]["target"] == daily["decision"]["target_core_exposure"]
                assert daily["decision"] == original["decision"]
                assert trace["baseline_drift"] == 0
            if date.fromisoformat(day) >= START:
                if base is None:
                    assert day == START.isoformat()
                    base = nav
                peak = max(peak or nav, nav)
                maximum_drawdown = min(maximum_drawdown, nav/peak - 1)
                measured += 1
            if key == "owned55" and previous and trace["owned55"]["active"] and not previous["owned55"]["active"]:
                events.append(dict(type="entry", date=day, current_target=trace["current"]["target"], owned55_target=trace["owned55"]["target"]))
            if key == "owned55" and previous and not trace["owned55"]["active"] and previous["owned55"]["active"]:
                events.append(dict(type="recovery", date=day, current_target=trace["current"]["target"], owned55_target=trace["owned55"]["target"]))
            previous = trace
        reported = json.loads((segments[-1]/"comparison-status.json").read_text())["control" if key == "current" else key]
        multiple = nav/base
        cagr = math.expm1(math.log(float(multiple))*365.2425/(date.fromisoformat(END)-START).days)
        assert measured == reported["sessions"] == 5032
        assert base == Decimal(reported["base"])
        assert abs(multiple - Decimal(reported["multiple"])) < Decimal("1e-25")
        assert abs(maximum_drawdown - Decimal(reported["drawdown"])) < Decimal("1e-25")
        assert abs(cagr - reported["cagr"]) < 1e-12
        summary[key] = dict(final_nav=str(nav), base=str(base), multiple=str(multiple),
                            cagr=cagr, maximum_drawdown=str(maximum_drawdown), sessions=measured)
        if key == "owned55":
            summary[key]["cause_events"] = events
    exposures = []
    first_difference = None
    for trace in all_trace:
        current, owned = trace["current"]["target"], trace["owned55"]["target"]
        if current != owned:
            first_difference = first_difference or trace["session"]
            exposures.append(trace["session"])
        assert owned <= current
    episodes = []
    for entry, recovery in zip(summary["owned55"]["cause_events"][::2],
                               summary["owned55"]["cause_events"][1::2], strict=True):
        start = next(i for i, row in enumerate(all_trace) if row["session"] == entry["date"])
        finish = next(i for i, row in enumerate(all_trace) if row["session"] == recovery["date"])
        assert start < finish
        def relative(row):
            return Decimal(row["owned55_economics"]["strategy_nav"])/Decimal(row["current_economics"]["strategy_nav"])
        relative_before = relative(all_trace[start-1])
        relative_after = relative(all_trace[finish])
        episode = dict(entry=entry["date"], recovery=recovery["date"],
                       sessions=finish-start, entry_targets=[entry["current_target"], entry["owned55_target"]],
                       relative_ratio_before=str(relative_before), relative_ratio_after=str(relative_after),
                       relative_change=str(relative_after/relative_before-1))
        episodes.append(episode)
    return dict(status="PASS", total_sessions=len(all_trace), measurement_start=START.isoformat(),
                end=END, segments=bounds, first_target_difference=first_difference,
                differing_target_sessions=len(exposures), episodes=episodes, **summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.root), indent=2))
