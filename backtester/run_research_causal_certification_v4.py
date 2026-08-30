#!/usr/bin/env python3
"""Run the finalized schema-aware retained-research causal certification."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester import run_research_causal_certification as base


def _dated_future_rows(path: Path, cutoff: str, candidates: tuple[str, ...]) -> int:
    columns = list(pd.read_csv(path, compression="gzip", nrows=0).columns)
    date_column = next((name for name in candidates if name in columns), None)
    if date_column is None:
        raise RuntimeError(f"{path.name} has no causal date column in {candidates}")
    frame = pd.read_csv(path, compression="gzip", usecols=[date_column], dtype=str)
    return int((frame[date_column].astype(str) > cutoff).sum())


def _future_source_counts(dataset: Path, cutoff: str) -> dict[str, int]:
    counts = {
        "metadata": _dated_future_rows(
            dataset / "metadata-timeline.csv.gz", cutoff, ("effective_session", "session")
        ),
        "corporate_actions": _dated_future_rows(
            dataset / "actions.csv.gz", cutoff, ("effective_session", "session")
        ),
        "terminal_events": _dated_future_rows(
            dataset / "terminal-events.csv.gz", cutoff, ("effective_session", "session")
        ),
        "benchmark": _dated_future_rows(
            dataset / "benchmark.csv.gz", cutoff, ("session", "effective_session")
        ),
        "cash": _dated_future_rows(
            dataset / "cash.csv.gz", cutoff, ("session", "effective_session")
        ),
    }
    observation_rows = 0
    for path in sorted(dataset.glob("observations-*.csv.gz")):
        observation_rows += _dated_future_rows(path, cutoff, ("session", "date"))
    counts["prices_volume_eligibility"] = observation_rows
    return counts


def _run_single(
    *, dataset: Path, output: Path, variant: str, cutoff: str | None
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(ROOT / "backtester/run_research_causal_single_v4.py"),
        "--canonical-dataset",
        str(dataset),
        "--output",
        str(output),
        "--variant",
        variant,
        "--end-session",
        "2007-12-31",
    ]
    if cutoff:
        command.extend(("--cutoff", cutoff))
    log_path = output / "single-run.log"
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
    manifest_path = output / "causal-run-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"single run omitted manifest: {output}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if variant == "poison":
        assert cutoff is not None
        source_counts = _future_source_counts(dataset, cutoff)
        poison_counts = manifest["runtime"]["poison_counts"]
        failures = []
        for domain, source_count in sorted(source_counts.items()):
            poisoned = int(poison_counts.get(domain, 0))
            if source_count > 0 and poisoned <= 0:
                failures.append(
                    {"domain": domain, "future_source_rows": source_count, "poisoned": poisoned}
                )
        if failures:
            raise RuntimeError(
                "future poison omitted populated domains: "
                + json.dumps(failures, sort_keys=True)
            )
        manifest["future_source_counts"] = source_counts
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return manifest


base._run_single = _run_single

if __name__ == "__main__":
    raise SystemExit(base.main())
