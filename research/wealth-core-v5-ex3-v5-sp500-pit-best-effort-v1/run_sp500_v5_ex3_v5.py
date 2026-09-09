#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADVERSARIAL_DIR = HERE.parent / "wealth-core-v5-sentinel-ex3-v5-adversarial-v1"
if str(ADVERSARIAL_DIR) not in sys.path:
    sys.path.insert(0, str(ADVERSARIAL_DIR))

import run_adversarial as adv

SCHEMA = "research.wealth-core-v5-ex3-v5-sp500-pit-best-effort/1"
SYSTEM = "Wealth Core V5 + Sentinel EX3 V5"
UNIVERSE = "S&P 500 PIT best effort"
EXPECTED_MEMBERSHIP_HASH = "1981828b71073be4d0fcf4addb37a56c844a29219090eb0c8fbc535d393bdb2d"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def patch_sp500_pit(src: str) -> str:
    loader_marker = "PIT_MODE = MODE == 'fullpit'\n"
    loader = r'''PIT_MODE = MODE == 'fullpit'

# Research-only S&P 500 best-effort PIT universe gate.  The materialized
# segment tape is causal by session and keyed to the same Sharadar security_id
# namespace consumed by the canonical PIT replay.
_SP500_SEGMENT_PATH = Path(os.environ['SP500_PIT_SEGMENTS'])
_SP500_SEGMENTS = pd.read_csv(
    _SP500_SEGMENT_PATH,
    compression='gzip',
    dtype=str,
    usecols=['security_id', 'segment_from', 'segment_until_exclusive'],
    keep_default_na=False,
)
_SP500_EVENTS = []
for _r in _SP500_SEGMENTS.itertuples(index=False):
    _sid = str(_r.security_id)
    _start = str(_r.segment_from)
    _until = str(_r.segment_until_exclusive)
    _SP500_EVENTS.append((_start, 1, _sid))
    if _until:
        _SP500_EVENTS.append((_until, -1, _sid))
_SP500_EVENTS.sort(key=lambda _x: (_x[0], _x[1]))
_SP500_EVENT_CURSOR = 0
_SP500_ACTIVE_COUNTS = {}
_SP500_LAST_SESSION = ''

def _sp500_active_on(_ds):
    global _SP500_EVENT_CURSOR, _SP500_LAST_SESSION
    if _SP500_LAST_SESSION and _ds < _SP500_LAST_SESSION:
        raise RuntimeError(f'S&P PIT session order regressed: {_ds} < {_SP500_LAST_SESSION}')
    while _SP500_EVENT_CURSOR < len(_SP500_EVENTS) and _SP500_EVENTS[_SP500_EVENT_CURSOR][0] <= _ds:
        _event_ds, _delta, _sid = _SP500_EVENTS[_SP500_EVENT_CURSOR]
        _new = int(_SP500_ACTIVE_COUNTS.get(_sid, 0)) + int(_delta)
        if _new < 0:
            raise RuntimeError(f'S&P PIT negative active count for {_sid} at {_event_ds}')
        if _new:
            _SP500_ACTIVE_COUNTS[_sid] = _new
        else:
            _SP500_ACTIVE_COUNTS.pop(_sid, None)
        _SP500_EVENT_CURSOR += 1
    _SP500_LAST_SESSION = _ds
    return _SP500_ACTIVE_COUNTS
'''
    src = adv.replace_once(src, loader_marker, loader, "S&P PIT loader seam")

    elig_marker = "            elig=_sec_ok&_base_elig\n"
    elig_patch = (
        "            _sp500_active=_sp500_active_on(ds)\n"
        "            _sp500_ok=np.fromiter((str(sid[int(_tid)]) in _sp500_active for _tid in tids),dtype=bool,count=len(tids))\n"
        "            elig=_sec_ok&_base_elig&_sp500_ok\n"
    )
    src = adv.replace_once(src, elig_marker, elig_patch, "S&P PIT eligibility seam")
    if src.count("elig=_sec_ok&_base_elig&_sp500_ok") != 1:
        raise RuntimeError("S&P PIT universe gate was not bound exactly once")
    return src


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    summary_path = Path(os.environ["SP500_PIT_SUMMARY"])
    segment_path = Path(os.environ["SP500_PIT_SEGMENTS"])
    universe_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if universe_summary.get("status") != "BEST_EFFORT_RUNNABLE":
        raise RuntimeError("S&P best-effort universe is not runnable")
    if universe_summary.get("best_effort_pit") is not True or universe_summary.get("formal_pit_certified") is not False:
        raise RuntimeError("S&P universe claim boundary changed")
    if universe_summary.get("membership_dataset_hash") != EXPECTED_MEMBERSHIP_HASH:
        raise RuntimeError("S&P membership authority hash changed")
    if universe_summary.get("window_end") != "2026-07-31":
        raise RuntimeError("S&P universe does not reach replay end")

    selected = adv.build_selected(args.control_source, args.median_overlay)
    selected = patch_sp500_pit(selected)

    args.output.mkdir(parents=True, exist_ok=True)
    replay = adv.execute(selected, args.output / "replay", "sp500_v5_ex3_v5", keep_raw=True)

    result = {
        "schema": SCHEMA,
        "status": "PASS_FRESH_FULL_PIT_REPLAY",
        "system": SYSTEM,
        "universe": {
            "name": UNIVERSE,
            "claim": "BEST_EFFORT_PIT_VIABILITY",
            "formal_pit_certified": False,
            "membership_dataset_hash": universe_summary["membership_dataset_hash"],
            "window_start": universe_summary["window_start"],
            "window_end": universe_summary["window_end"],
            "daily_constituents": universe_summary.get("daily_constituents"),
            "excluded_source_sessions": universe_summary.get("excluded_source_sessions"),
            "exclusion_fraction_of_source_membership_sessions": universe_summary.get("exclusion_fraction_of_source_membership_sessions"),
            "segments_sha256": sha256_file(segment_path),
            "summary_sha256": sha256_file(summary_path),
        },
        "configuration": {
            "wealth_core": "V5",
            "sentinel": "EX3 V5",
            "slots": 20,
            "measurement_start": adv.START,
            "measurement_end": adv.END,
            "measurement_sessions": adv.SESSIONS,
        },
        "validation": {
            "fresh_full_pit": True,
            "v5_contract_guard": True,
            "sentinel_ex3_v5_guard": True,
            "causal_timing_guard": True,
            "sp500_daily_security_id_gate": True,
        },
        "metrics": {
            "wealth_core": replay["core"],
            "wealth_core_plus_sentinel": replay["sentinel"],
        },
        "allocation": replay.get("allocation"),
        "buys": replay.get("buys"),
        "sells": replay.get("sells"),
        "gap_clipped_entries": replay.get("gap_clipped_entries"),
        "blocked_open_entries": replay.get("blocked_open_entries"),
        "canonical_pit_dataset_sha256": replay.get("dataset_sha256"),
    }
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
