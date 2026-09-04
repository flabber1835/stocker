#!/usr/bin/env python3
"""Preflight-fixed launcher for the Strategy 9 architecture-defect E1/E2 replay."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from backtester import experiment_architecture_defects_2018 as base


def transformed_source(output: Path) -> str:
    text = base.strategy9.transformed_source(output)

    # corrected_warmup_cash inserts _cash_frame/_CASH_YIELD between CandidateB
    # and bil_factors. Preserve that causal cash initialization explicitly.
    pattern = r"class CandidateA:.*?(?=\n_cash_frame=)"
    text, count = re.subn(
        pattern,
        base.CANDIDATE_CLASSES.rstrip() + "\n",
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(f"candidate class seam: expected one match, got {count}")

    text = base.replace_once(
        text,
        "a_d,a_reason=ca.step(native_target,recent_r20,spy20)",
        "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20,r40)",
        "E1 call",
    )
    text = base.replace_once(
        text,
        "b_d,b_reason=cb.step(native_target,recent_r20,spy20)",
        "b_d,b_reason=cb.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20)",
        "E2 call",
    )
    text = base.replace_once(
        text,
        "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,",
        "'recent_r20':recent_r20,'recent_r40':recent_r40,'wc_r20':r20,'wc_r40':r40,'spy_r20':spy20,",
        "owned-book audit returns",
    )
    if "_CASH_YIELD=" not in text or "_cash_frame=" not in text:
        raise RuntimeError("causal cash initialization missing after source transform")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path("/tmp/broad_simplified_architecture_defects_e1_e2_v2.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(f"[RUN] {base.LABEL} candidates={base.E1},{base.E2}", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    base.finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
