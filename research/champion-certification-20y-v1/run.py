"""One authorized frozen-champion replay with auditable PIT portfolio weights."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

import numpy as np
import pandas as pd

from composition import Observer, SOURCE_SHA256, instrument, require
from publication import api, finalize

HERE = Path(__file__).resolve().parent
TRACK = "compact_simplified_no_ramp"
CHAMPION_COMMIT = "f6ad7b543fbd20ffe363127d1120f4472caa9360"
REFERENCE_COMMIT = "05727f2c65a235306fa55d61f254e06bed351776"
DATASET = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
HARNESS = "eaddca3f04f279e99663f832bf7293e92ee15662"
SLOT_REF = "refs/heads/research-budget/champion-certification-20y-v1/slot-01"


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def claim(output):
    receipt = dict(ref=SLOT_REF, slot=1, sha=os.environ["GITHUB_SHA"],
                   run_id=os.environ["GITHUB_RUN_ID"], run_attempt=os.environ["GITHUB_RUN_ATTEMPT"])
    result = api("/git/refs", {"ref": SLOT_REF, "sha": receipt["sha"]})
    require(result["ref"] == SLOT_REF and result["object"]["sha"] == receipt["sha"], "slot receipt mismatch")
    write(output / "SLOT.json", receipt)
    print("[SLOT_CLAIMED] " + json.dumps(receipt), flush=True)
    return receipt


def verify_export_rows(rows, sessions):
    stock = rows[rows.bucket == "STOCK"]
    require(not stock.duplicated(["date", "security_id"]).any(), "duplicate exported position")
    require((stock.ticker.str.len() > 0).all() and
            (stock.metadata_effective_session <= stock.date).all(), "PIT ticker dates")
    require(set(rows.date) == set(sessions.date), "composition/session coverage")
    expected_equity = rows.date.map(sessions.set_index("date").core_equity).to_numpy(float)
    require(np.allclose(rows.core_equity, expected_equity, rtol=1e-12, atol=1e-8), "row equity differs")
    values = rows.reference_value.to_numpy(float)
    require(np.isfinite(values).all() and (values >= 0).all(), "invalid reference values")
    require(np.allclose(stock.quantity.astype(float) * stock.mark.astype(float),
                        stock.reference_value.astype(float), rtol=1e-12, atol=1e-8), "quantity/mark value differs")
    by_date = rows.groupby("date").reference_value.sum()
    require(np.allclose(by_date.reindex(sessions.date), sessions.core_equity, rtol=1e-12, atol=1e-7), "exported equity sum")
    weights = 100 * values / expected_equity
    require(np.allclose(rows.shadow_weight_pct, weights, rtol=1e-12, atol=1e-8), "shadow row weights differ")
    bill = (rows.bucket == "TBILL_SLEEVE").to_numpy()
    for exposure, weight, target in (("effective_exposure_pct", "effective_model_weight_pct", "effective_exposure_pct"),
                                     ("close_desired_exposure_pct", "next_target_model_weight_pct", "close_desired_exposure_pct")):
        fraction = rows.date.map(sessions.set_index("date")[target]).to_numpy(float) / 100
        require(np.allclose(rows[exposure], fraction * 100, rtol=0, atol=1e-10), "row exposure clock differs")
        expected = np.where(bill, 100 * (1 - fraction), weights * fraction)
        require(np.allclose(rows[weight], expected, rtol=1e-12, atol=1e-8), f"{weight} arithmetic differs")
    for key in ("shadow_weight_pct", "effective_model_weight_pct", "next_target_model_weight_pct"):
        values = rows[key].to_numpy(float)
        require(np.isfinite(values).all() and (values >= 0).all(), f"invalid {key}")
        require(np.allclose(rows.groupby("date")[key].sum(), 100., rtol=0, atol=1e-8), f"{key} sum")
    return stock


def check_composition(output, daily, observations):
    sessions = pd.read_csv(output / "portfolio-sessions.csv", dtype={"date": str})
    require(len(sessions) == len(observations) == 5176, "observation coverage mismatch")
    require(sessions.date.tolist() == observations.date.dt.strftime("%Y-%m-%d").tolist(), "observer dates differ")
    require(sessions.date.iloc[0] == "2006-01-03" and sessions.date.iloc[-1] == "2026-07-31", "warmup horizon mismatch")
    require(sessions.date.is_monotonic_increasing and not sessions.date.duplicated().any(), "observer ordering")
    measured = sessions.loc[sessions.phase == "MEASUREMENT"].reset_index(drop=True)
    require(len(measured) == len(daily) == 5032, "measurement coverage mismatch")
    require(measured.date.tolist() == daily.date.dt.strftime("%Y-%m-%d").tolist(), "measured dates differ")
    for a, b in (("core_equity", "shadow_equity"), ("effective_exposure_pct", "A_allocation")):
        scale = 100 if a.endswith("pct") else 1
        require(np.allclose(measured[a], daily[b] * scale, rtol=1e-12, atol=1e-8), f"observer {a} differs")
    mismatches = sum(sorted(json.loads(a)) != sorted(json.loads(b))
                     for a, b in zip(measured.held_ids_json, daily.research_selected_positions))
    require(mismatches == 0, "exported holdings differ from engine holdings")
    require(np.array_equal(measured.close_desired_exposure_pct.to_numpy(),
                           observations.loc[observations.measured, "current_close_desired"].to_numpy()*100),
            "close target observer timing differs")
    rows = pd.read_csv(output / "portfolio-composition.csv", keep_default_na=False,
                       dtype={"date": str, "security_id": str})
    stock = verify_export_rows(rows, sessions)
    return dict(status="PASS", observations=len(sessions), measured_sessions=len(measured),
                composition_rows=len(rows), stock_rows=len(stock), unique_securities=stock.security_id.nunique(),
                held_id_mismatches=mismatches, weight_sums="100% on every date in all three bases",
                carried_mark_holding_days=int(sessions.carried_mark_count.sum()),
                unknown_canonical_type_holding_days=int(sessions.unknown_canonical_type_count.sum()))


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    champion = args.champion_root.resolve()
    sys.path.insert(0, str(champion))
    import ablation_reference as reference
    import variants
    import run_experiment as replay

    source = (champion / "sources" / (TRACK + ".py")).read_text()
    selected = instrument(source)
    expected_dir = champion / "results/34528401951-1/cases/baseline"
    expected_core = json.loads((expected_dir / "CORE_RESULT.json").read_text())
    expected = json.loads((expected_dir / "RESULT.json").read_text())
    require(expected["status"] == "PASS", "reference case incomplete")
    require(expected["sources"][TRACK]["sha256"] == SOURCE_SHA256, "reference source differs")
    require(expected_core["dataset_sha256"] == DATASET, "reference dataset differs")
    prior = replay.read_csv(expected_dir / "daily-tracks.csv.gz")
    base = reference.load(args.runner.resolve())
    require(base.SELECTED == reference.EXPECTED_V6, "V6 configuration differs")
    base.timing_guard(selected)
    write(output / "PROVENANCE.json", dict(
        schema="research.champion-certification-20y/1", source_sha256=SOURCE_SHA256,
        champion_commit=CHAMPION_COMMIT, reference_commit=REFERENCE_COMMIT,
        harness_commit=HARNESS, dataset_sha256=DATASET,
        launch_commit=os.environ["GITHUB_SHA"], run_id=os.environ["GITHUB_RUN_ID"],
        instrumented_source_sha256=hashlib.sha256(selected.encode()).hexdigest(),
        source_ast_preserved=True, python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
        classification_scenario=os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"],
        classification_overlay_sha256=sha(Path(os.environ["BEST_EFFORT_SECURITY_TYPES"])),
        production_certification=False, new_out_of_sample_evidence=False,
    ))
    (output / "champion-source.py").write_text(source)
    (output / "runtime-packages.txt").write_text(subprocess.check_output(
        [sys.executable, "-m", "pip", "freeze", "--all"], text=True))
    holder, claims = {}, []
    observer = Observer(output)
    def prepare(module):
        require(not claims, "second Core start refused")
        holder["module"] = module
        module._cert_observe = observer
        claims.append(claim(output))
    execute = inspect.getsource(base.execute)
    seam = "    module.OUT = engine\n    module.run()"
    require(execute.count(seam) == 1, "one-start driver seam differs")
    execute = execute.replace(seam, "    module.OUT = engine\n    prepare(module)\n    module.run()", 1)
    environment = dict(base.__dict__, prepare=prepare)
    exec(compile(execute, "<one-start-certification>", "exec"), environment)
    try:
        result = environment["execute"](selected, output / "core", "champion", False)
    finally:
        observer.close()
    write(output / "CORE_RESULT.json", result)
    require(len(claims) == 1, "Core start count")
    for key in ("core_tape_sha256", "transactions_sha256", "close_decisions_sha256", "dataset_sha256"):
        require(result[key] == expected_core[key], f"frozen {key} differs")
    metrics = expected["tracks"][TRACK]["metrics"]
    for window, fields in metrics.items():
        for name in ("cagr", "max_drawdown", "sharpe_daily_252", "ending_multiple"):
            require(abs(result["sentinel"][window][name] - fields[name]) <= 5e-10,
                    f"headline mismatch {window}/{name}")
    daily = replay.read_csv(output / "core/engine/daily.csv")
    observations = replay.read_csv(output / "observations.csv")
    observations["measured"] = observations.measured.map(reference._as_bool)
    module = holder["module"]
    pure = variants.pure(source)
    frame, audit = replay.replay(module, observations, pure["Native"], pure["CandidateA"])
    restarted, restart_audit = replay.replay(module, observations, pure["Native"], pure["CandidateA"], restart=True)
    minimal = variants.pure((champion / "sources/simplified_no_ramp.py").read_text())
    compact_reference, _ = replay.replay(module, observations, minimal["Native"], minimal["CandidateA"])
    mapping = {TRACK + "_" + c: c for c in frame.columns if c != "date"}
    checks = dict(
        source_ast="PASS",
        frozen_core_hashes="PASS",
        frozen_daily=replay.require_pair(frame, prior.rename(columns=mapping), 1e-10),
        fresh_engine=replay.require_pair(frame, daily.rename(columns={
            "A_allocation": "allocation", "A_nav": "nav", "A_reason": "close_reason"}), 1e-10),
        compact_reference=replay.require_pair(frame, compact_reference),
        restart=replay.require_pair(frame, restarted),
        restart_checkpoints=restart_audit["restarts"],
        composition=check_composition(output, daily, observations),
    )
    require(audit["episodes"] == restart_audit["episodes"] and
            audit["concordance_releases"] == restart_audit["concordance_releases"], "restart audits differ")
    frame.to_csv(output / "champion-daily.csv", index=False)
    (output / "canonical-manifest.json").write_text(json.dumps(module._CANONICAL.manifest, indent=2, sort_keys=True)+"\n")
    write(output / "RESULT.json", dict(
        status="PASS_RESEARCH_CHAMPION_CERTIFICATION", track=TRACK, slot=claims[0],
        source_sha256=SOURCE_SHA256, dataset_sha256=DATASET, metrics=result["sentinel"],
        allocation=result["allocation"], checks=checks, core=result,
        production_certification=False, production_promotion_authorized=False,
        prior_economic_preservation="FAIL", prior_robustness="FAIL",
    ))
    print("[CERTIFICATION_HEADLINE] " + json.dumps(result["sentinel"]["20"]), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--champion-root", type=Path, required=True)
    ap.add_argument("--runner", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    require(not args.output.exists(), "output already exists; preserved evidence cannot be overwritten")
    try:
        run(args)
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        write(args.output / "FAILURE.json", dict(status="FAIL", error_type=type(exc).__name__,
              error=str(exc), traceback=traceback.format_exc(), full_pit_retry_authorized=False))
        raise
    finally:
        finalize(args.output)


if __name__ == "__main__":
    main()
