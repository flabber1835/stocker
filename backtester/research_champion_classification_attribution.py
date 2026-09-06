#!/usr/bin/env python3
"""Controlled security-type attribution replays for the frozen Research Champion.

Endpoints are the previously reviewed classification path and the corrected historical
classification path. These isolated replays change exactly one demonstrated historical
classification family at a time. Results are attribution diagnostics, not certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from backtester import research_champion_best_effort_classification as base
from backtester import research_champion_corrected_classification as corrected

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("pds_only", "eqm_only")
PDS = "594891209465982980"
EQM = "192545371416014112"
LABEL = "ATTRIBUTION_DIAGNOSTIC_NOT_CERTIFIED"


class SecurityTypeEstimate(corrected.SecurityTypeEstimate):
    def __init__(self, ledger: Path, scenario: str, reviewed_ledger: Path = base.DEFAULT_REVIEWED_LEDGER,
                 correction_ledger: Path = corrected.CORRECTION_LEDGER):
        super().__init__(ledger, scenario, reviewed_ledger, correction_ledger)
        variant = os.environ.get("CHAMPION_CLASSIFICATION_ATTRIBUTION_VARIANT", "")
        if variant not in VARIANTS:
            raise RuntimeError(f"unsupported classification attribution variant: {variant}")
        self.variant = variant
        keep = PDS if variant == "pds_only" else EQM
        self.corrections = {keep: self.corrections[keep]}
        self.correction_calls = {"common": 0, "non_common": 0}

    def summary(self) -> dict:
        result = super().summary()
        result.update(
            label=LABEL,
            scenario=f"classification_attribution_{self.variant}",
            attribution_variant=self.variant,
            attribution_semantics=(
                "Causal Champion replay with only the named authoritative classification correction applied; "
                "all Champion economics and other reviewed classifications remain frozen."
            ),
            certification_eligible=False,
        )
        return result


def install(text: str) -> str:
    text = corrected.install(text)
    old = "from backtester import research_champion_corrected_classification as _bestclass"
    new = "from backtester import research_champion_classification_attribution as _bestclass"
    if text.count(old) != 1:
        raise RuntimeError("attribution overlay import seam is not unique")
    text = text.replace(old, new, 1)
    compile(text, "<Champion-classification-attribution>", "exec")
    return text


def build_source(output: Path) -> str:
    from backtester import run_research_champion_pit_closure_20y as closure
    return install(closure.build_source(output))


def _mark(output: Path, variant: str) -> None:
    import pandas as pd

    scenario = f"classification_attribution_{variant}"
    for name in ("summary.json", "pit-closure-replay-identity.json"):
        path = output / name
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.update(
            status=LABEL,
            certification_status="NOT_CERTIFIED",
            classification_scenario=scenario,
            attribution_variant=variant,
            attribution_diagnostic=True,
            attribution_semantics=(
                "Actual causal frozen-Champion replay changing only the named historical security-type correction."
            ),
            historical_correction_ledger_sha256=corrected.CORRECTION_LEDGER_SHA256,
        )
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name in ("metrics.csv", "daily.csv.gz"):
        path = output / name
        frame = pd.read_csv(path)
        frame["classification_scenario"] = scenario
        frame["certification_status"] = "NOT_CERTIFIED"
        frame["attribution_variant"] = variant
        if name.endswith(".gz"):
            frame.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
        else:
            frame.to_csv(path, index=False)
    evidence = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt")
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{base._sha256(path)}  {path.name}\n" for path in evidence), encoding="utf-8"
    )


def run(output: Path, variant: str, ledger: Path = base.DEFAULT_LEDGER) -> int:
    from backtester import run_research_champion_pit_closure_20y as closure

    if variant not in VARIANTS:
        raise RuntimeError(f"unsupported classification attribution variant: {variant}")
    if os.environ.get("PIT_OFFICIAL_BACKTEST", "0") not in ("", "0"):
        raise RuntimeError("classification attribution replay requires PIT_OFFICIAL_BACKTEST=0")
    original = closure.build_source
    closure.build_source = lambda destination: install(original(destination))
    os.environ["BEST_EFFORT_SECURITY_TYPES"] = str(ledger.resolve())
    os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"] = "reviewed_18"
    os.environ["CHAMPION_CLASSIFICATION_ATTRIBUTION_VARIANT"] = variant
    try:
        rc = closure.run(output)
    finally:
        closure.build_source = original
    if rc:
        return rc
    base._rewrite_outputs(output.resolve(), "reviewed_18")
    _mark(output.resolve(), variant)
    print(f"[ATTRIBUTION REPLAY] {variant} completed; diagnostic, NOT certified", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--ledger", type=Path, default=base.DEFAULT_LEDGER)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    os.environ["BEST_EFFORT_SECURITY_TYPES"] = str(args.ledger.resolve())
    os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"] = "reviewed_18"
    os.environ["CHAMPION_CLASSIFICATION_ATTRIBUTION_VARIANT"] = args.variant
    if args.self_test:
        source = build_source(args.output)
        value = SecurityTypeEstimate(args.ledger, "reviewed_18")
        print(json.dumps({
            "status": "PASS",
            "variant": args.variant,
            "generated_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "active_correction_security_ids": sorted(value.corrections),
            "certification_eligible": False,
        }, sort_keys=True))
        return 0
    return run(args.output, args.variant, args.ledger)


if __name__ == "__main__":
    raise SystemExit(main())
