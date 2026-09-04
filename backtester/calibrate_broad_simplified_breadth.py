#!/usr/bin/env python3
"""Calibration experiment for the simplified broad PIT-estimate architecture.

Baseline: experiment2_broad_independent_correlation.py

Forensic calibration hypothesis:
- correlation-peer damaged breadth runs slightly hotter than the retired sector
  breadth scale, creating one clearly marginal FAST event (2025-04-07) and
  delaying recovery in 2010;
- Wealth Core, green breadth, universe, ranking, sizing, exits, peer topology,
  SLOW, ramp, and LD-RC remain frozen.

Single domain calibration:
- FAST damaged threshold: 0.85 -> 0.875
- healthy/recovery damaged ceiling: 0.60 -> 0.625

No return series is used by this wrapper to choose or adapt parameters at run time.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from backtester import experiment2_broad_independent_correlation as base
from backtester import run_research_ldrc_corrected_warmup_cash as corrected

LABEL = "BROAD_SIMPLIFIED_BREADTH_CALIBRATION_0875_0625"
FAST_DAMAGED = 0.875
HEALTHY_DAMAGED = 0.625


def transformed_source(output: Path) -> str:
    text = base.transformed_source(output)

    old_fast = "FAST = {'dd':-.10,'dam':.85,'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10}"
    new_fast = "FAST = {'dd':-.10,'dam':.875,'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10}"
    if text.count(old_fast) != 1:
        raise RuntimeError(f'FAST calibration seam count={text.count(old_fast)}')
    text = text.replace(old_fast, new_fast, 1)

    old_healthy = "healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<=.60 and green>=.20"
    new_healthy = "healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<=.625 and green>=.20"
    if text.count(old_healthy) != 1:
        raise RuntimeError(f'healthy calibration seam count={text.count(old_healthy)}')
    text = text.replace(old_healthy, new_healthy, 1)

    return text


def finalize(output: Path) -> None:
    base.finalize(output)

    summary_path = output / 'summary.json'
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    summary['experiment'] = 'broad_simplified_breadth_calibration'
    summary['evidence_label'] = LABEL
    summary['calibration'] = {
        'kind': 'correlation_breadth_scale_calibration',
        'fast_damaged_baseline': 0.85,
        'fast_damaged_calibrated': FAST_DAMAGED,
        'healthy_damaged_baseline': 0.60,
        'healthy_damaged_calibrated': HEALTHY_DAMAGED,
        'slow_parameters_changed': False,
        'ldrc_parameters_changed': False,
        'ramp_parameters_changed': False,
        'wealth_core_parameters_changed': False,
        'peer_definition_changed': False,
        'rationale': (
            'forensic broad-history translation of the damaged-breadth scale: '
            'filter marginal correlation-peer FAST events while admitting near-threshold '
            'healthy recovery sessions; all other mechanics frozen'
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    manifest_path = output / 'experiment2-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['schema'] = 'backtester.broad-simplified-breadth-calibration/1'
    manifest['evidence_label'] = LABEL
    manifest['experiment'] = summary['experiment']
    manifest['calibration'] = summary['calibration']
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    files = [output/'daily.csv.gz', output/'metrics.csv', summary_path, manifest_path]
    (output/'SHA256SUMS.txt').write_text(
        ''.join(f"{corrected.old.sha256(p)}  {p.name}\n" for p in files),
        encoding='utf-8',
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path('/tmp/broad_simplified_breadth_calibration.py')
    generated.write_text(transformed_source(args.output), encoding='utf-8')
    env = dict(os.environ)
    env['RESEARCH_REPLAY_MODE'] = 'fullpit'
    print(
        f'[RUN] {LABEL} FAST.dam={FAST_DAMAGED:.3f} healthy.dam<={HEALTHY_DAMAGED:.3f}',
        flush=True,
    )
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
