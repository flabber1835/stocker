#!/usr/bin/env python3
"""Experiment 3: R1000 structural candidate-breadth calibration.

This is the single calibration experiment selected after experiments 1 and 2.
It changes only Wealth Core's candidate-pool breadth. Recent-leadership breadth
remains 10% and all ranking, sizing, exit, admission, Sentinel correlation-peer,
and LD-RC parameters remain frozen.

The candidate fraction is not return-fitted. It is derived mechanically from
experiment 2's broad/R1000 eligible-universe geometry:
    median(broad_eligible / r1000_eligible) = 1.5788177339901477
    candidate_fraction = 0.10 * median_ratio = 0.15788177339901477
This makes the median R1000 candidate population match the broad 10% candidate
population (about 142 names) while leaving the R1000 leadership witness at 10%.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from backtester import run_r1000_correlation_peers as rbase
from backtester import run_r1000_correlation_peers_v2 as v2

LABEL = "EXPERIMENT_3_R1000_GEOMETRY_CALIBRATION"
ELIGIBLE_RATIO_MEDIAN = 1.5788177339901477
CANDIDATE_TOP = 0.15788177339901477


def transformed_source(output: Path) -> str:
    text = v2.transformed_source(output)

    marker = "TOP = 0.10\n\nR1000_PATH"
    replacement = f"TOP = 0.10\nCANDIDATE_TOP = {CANDIDATE_TOP!r}\n\nR1000_PATH"
    if text.count(marker) != 1:
        raise RuntimeError(f"candidate constant seam count={text.count(marker)}")
    text = text.replace(marker, replacement, 1)

    old = "nk=min(len(et),max(25,int(math.ceil(len(et)*TOP)))); pool=rawall[:nk]"
    new = "nk=min(len(et),max(25,int(math.ceil(len(et)*TOP)))); cand_n=min(len(et),max(25,int(math.ceil(len(et)*CANDIDATE_TOP)))); pool=rawall[:cand_n]"
    if text.count(old) != 1:
        raise RuntimeError(f"candidate pool seam count={text.count(old)}")
    text = text.replace(old, new, 1)

    old_telemetry = "'leadership_population':int(nk),'held_count':int(len(held))"
    new_telemetry = "'leadership_population':int(nk),'candidate_population':int(cand_n),'held_count':int(len(held))"
    if text.count(old_telemetry) != 1:
        raise RuntimeError(f"candidate telemetry seam count={text.count(old_telemetry)}")
    text = text.replace(old_telemetry, new_telemetry, 1)
    return text


def finalize(output: Path, membership_manifest: Path) -> None:
    rbase.base.old.postprocess('fullpit', output)
    rbase.base.finalize('fullpit', output)
    rbase.finalize_experiment(output, membership_manifest)

    summary_path = output / 'summary.json'
    summary = json.loads(summary_path.read_text())
    summary['experiment'] = 'experiment3_r1000_candidate_geometry_calibration'
    summary['evidence_label'] = LABEL
    summary['calibration'] = {
        'kind': 'structural_geometry_not_return_fitted',
        'broad_to_r1000_eligible_ratio_median': ELIGIBLE_RATIO_MEDIAN,
        'leadership_fraction': 0.10,
        'candidate_fraction': CANDIDATE_TOP,
        'derivation': '0.10 * median broad/R1000 eligible-count ratio from experiment 2 aligned to active R1000 sessions',
        'baseline_r1000_median_candidate_population': 90,
        'broad_median_candidate_population': 142,
        'calibrated_r1000_median_candidate_population_expected': 142,
    }
    summary['domain_changes']['candidate_breadth'] = (
        f'candidate fraction {CANDIDATE_TOP:.12f}; leadership remains 0.10'
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')

    manifest_path = output / 'r1000-experiment-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['schema'] = 'backtester.r1000-exp3-candidate-geometry/1'
    manifest['evidence_label'] = LABEL
    manifest['experiment'] = summary['experiment']
    manifest['calibration'] = summary['calibration']
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')

    files = [output/'daily.csv.gz', output/'metrics.csv', summary_path, manifest_path]
    (output/'SHA256SUMS.txt').write_text(
        ''.join(f"{rbase.base.old.sha256(path)}  {path.name}\n" for path in files)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--membership', type=Path, required=True)
    ap.add_argument('--membership-manifest', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)

    generated = Path('/tmp/r1000_exp3_candidate_geometry.py')
    generated.write_text(transformed_source(args.output), encoding='utf-8')
    env = dict(os.environ)
    env['RESEARCH_REPLAY_MODE'] = 'fullpit'
    env['R1000_MEMBERSHIP_SNAPSHOTS'] = str(args.membership)
    print(f'[RUN] {LABEL} candidate_top={CANDIDATE_TOP:.12f} leadership_top=0.10', flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output, args.membership_manifest)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
