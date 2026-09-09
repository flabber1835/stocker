#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ALLOWED_SLOTS = tuple(range(18, 27))


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label} seam count must be exactly one; observed {count}")
    return text.replace(old, new, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", required=True, type=int, choices=ALLOWED_SLOTS)
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    canonical = Path(__file__).with_name("run_experiment.py")
    source = canonical.read_text()

    anchor = (
        "    variant = apply_open_time_whole_share_10bp(median5)\n"
        "    assert_contract(variant)\n"
    )
    replacement = (
        "    variant = apply_open_time_whole_share_10bp(median5)\n"
        "    slots = int(os.environ['WEALTH_CORE_STABILITY_SLOTS'])\n"
        "    if slots not in range(18, 27):\n"
        "        raise RuntimeError(f'unsupported stability slot count: {slots}')\n"
        "    entry_weight = 1.0 / float(slots)\n"
        "    entry_weight_literal = repr(entry_weight)\n"
        "    if variant.count('N_SLOTS = 20') != 1:\n"
        "        raise RuntimeError('canonical N_SLOTS seam is not unique')\n"
        "    if variant.count('ENTRY_W = 0.05') != 1:\n"
        "        raise RuntimeError('canonical ENTRY_W seam is not unique')\n"
        "    variant = variant.replace('N_SLOTS = 20', f'N_SLOTS = {slots}', 1)\n"
        "    variant = variant.replace('ENTRY_W = 0.05', f'ENTRY_W = {entry_weight_literal}', 1)\n"
        "    assert_contract(variant)\n"
    )
    source = replace_once(source, anchor, replacement, "variant injection")
    source = replace_once(
        source,
        '        "N_SLOTS = 20",\n',
        '        f"N_SLOTS = {slots}",\n',
        "N_SLOTS evidence",
    )
    source = replace_once(
        source,
        '        "ENTRY_W = 0.05",\n',
        '        f"ENTRY_W = {entry_weight_literal}",\n',
        "ENTRY_W evidence",
    )
    source = replace_once(
        source,
        '                "slots": 20,\n',
        '                "slots": slots,\n',
        "result slot telemetry",
    )
    source = replace_once(
        source,
        '                "target_entry_weight": 0.05,\n',
        '                "target_entry_weight": entry_weight,\n',
        "result entry-weight telemetry",
    )

    patched = canonical.with_name("_generated_portfolio_stability_runner.py")
    patched.write_text(source)
    env = os.environ.copy()
    env["WEALTH_CORE_STABILITY_SLOTS"] = str(args.slots)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(patched),
                "--control-source",
                str(args.control_source),
                "--median-overlay",
                str(args.median_overlay),
                "--output",
                str(args.output),
            ],
            env=env,
            check=False,
        )
    finally:
        patched.unlink(missing_ok=True)
    if proc.returncode != 0:
        return proc.returncode

    result_path = args.output / "RESULT.json"
    result = json.loads(result_path.read_text())
    cfg = result["wealth_core"]["configuration"]
    expected_weight = 1.0 / float(args.slots)
    if int(cfg["slots"]) != args.slots:
        raise RuntimeError("stability slot telemetry mismatch")
    if abs(float(cfg["target_entry_weight"]) - expected_weight) > 1e-15:
        raise RuntimeError("stability entry-weight telemetry mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
