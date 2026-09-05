#!/usr/bin/env python3
"""Kill reviewed Sentinel mutants in disposable import overlays."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[1])).resolve()
RUNTIME = Path("/app") if Path("/app/sentinel").is_dir() else REPO
TEST_SOURCE = Path("/work") if Path("/work/tests").is_dir() else REPO


@dataclass(frozen=True)
class Mutant:
    name: str
    relative_path: str
    original: str
    replacement: str
    test: str


MUTANTS = (
    Mutant(
        name="submit-before-send-pending",
        relative_path="sentinel/execution/executor.py",
        original=(
            "    pending = recovery.prepare_send(command)\n"
            "    journal.save_command(conn, pending, previous=command.state)\n\n"
            "    settled = await recovery.dispatch(broker, pending)\n"
        ),
        replacement=(
            "    pending = recovery.prepare_send(command)\n\n"
            "    settled = await recovery.dispatch(broker, pending)\n"
            "    journal.save_command(conn, pending, previous=command.state)\n"
        ),
        test=(
            "tests/sentinel/test_process_death_recovery.py::"
            "test_process_death_recovers_one_order_and_one_fill_without_duplication"
        ),
    ),
    Mutant(
        name="working-order-added-to-remaining-delta",
        relative_path="sentinel/execution/commands.py",
        original="    remaining = desired - held - committed\n",
        replacement="    remaining = desired - held + committed\n",
        test=(
            "tests/sentinel/test_execution_contract.py::TestRemainingDelta::"
            "test_a_working_order_is_COMMITTED_and_not_re_ordered"
        ),
    ),
    Mutant(
        name="ramp-requires-one-extra-healthy-session",
        relative_path="sentinel/controller/machine.py",
        original=(
            "            if st.get(\"ramp_healthy_streak\", 0) >= need:\n"
        ),
        replacement=(
            "            if st.get(\"ramp_healthy_streak\", 0) > need:\n"
        ),
        test=(
            "tests/sentinel/test_controller_certification.py::"
            "TestTheTapeIsReproduced::"
            "test_the_ramp_reproduces_candidate_alloc_on_EVERY_session"
        ),
    ),
    Mutant(
        name="position-order-gap-direction-reversed",
        relative_path="sentinel/execution/reconcile.py",
        original="        gap = expected_quantity - observed_quantity\n",
        replacement="        gap = expected_quantity + observed_quantity\n",
        test=(
            "tests/sentinel/test_journal_and_reconcile.py::"
            "TestReconciliation::"
            "test_position_endpoint_may_lead_exact_working_order_briefly"
        ),
    ),
    Mutant(
        name="corporate-actions-ignored-during-reconciliation",
        relative_path="sentinel/execution/reconcile.py",
        original="    lookup = actions or (lambda _sid: Decimal(1))\n",
        replacement="    lookup = lambda _sid: Decimal(1)\n",
        test=(
            "tests/sentinel/test_journal_and_reconcile.py::"
            "TestReconciliation::"
            "test_A_SPLIT_DURING_AN_OUTAGE_IS_NOT_FOREIGN_ACTIVITY"
        ),
    ),
    Mutant(
        name="same-session-metadata-excluded",
        relative_path="sentinel/core/loader.py",
        original=(
            '            "  MAX(snapshot_date) snapshot_date"\n'
            '            " FROM sentinel_universe u"\n'
            '            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"\n'
            '            "   AND snapshot_date<=%s AND " + visible_predicate("u") +\n'
        ),
        replacement=(
            '            "  MAX(snapshot_date) snapshot_date"\n'
            '            " FROM sentinel_universe u"\n'
            '            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"\n'
            '            "   AND snapshot_date<%s AND " + visible_predicate("u") +\n'
        ),
        test=(
            "tests/sentinel/test_issue209_session_effective_metadata.py::"
            "test_future_tickers_snapshot_cannot_change_missed_session"
        ),
    ),
    Mutant(
        name="next-open-session-check-inverted",
        relative_path="sentinel/core/decision.py",
        original="    if effective_session != expected_effective:\n",
        replacement="    if effective_session == expected_effective:\n",
        test=(
            "tests/sentinel/test_production_decision.py::"
            "test_plan_refuses_an_effective_session_other_than_next_xnys"
        ),
    ),
    Mutant(
        name="cash-residual-adds-invested-notional",
        relative_path="sentinel/execution/projection.py",
        original="    residual = nav - invested\n",
        replacement="    residual = nav + invested\n",
        test=(
            "tests/sentinel/test_projection_and_executor.py::"
            "TestProjection::"
            "test_the_defensive_sleeve_absorbs_what_the_core_did_not_take"
        ),
    ),
    Mutant(
        name="alpaca-submit-falls-back-to-mutable-symbol",
        relative_path="sentinel/execution/alpaca.py",
        original='            "symbol": str(instrument.broker_id),\n',
        replacement='            "symbol": str(instrument.symbol),\n',
        test=(
            "tests/sentinel/test_alpaca_certification_boundary.py::"
            "test_every_certified_alpaca_variant_submits_by_stable_asset_id"
        ),
    ),
    Mutant(
        name="illegal-command-transition-guard-disabled",
        relative_path="sentinel/execution/states.py",
        original="    if not can_transition(current, nxt):\n",
        replacement="    if False:\n",
        test=(
            "tests/sentinel/test_execution_state_machine_model.py::"
            "test_command_transition_guard_matches_every_independent_model_edge"
        ),
    ),
    Mutant(
        name="unknown-command-no-longer-blocks-overlap",
        relative_path="sentinel/execution/states.py",
        original=(
            "IN_FLIGHT = frozenset({S.SEND_PENDING, S.ACKNOWLEDGED, S.UNKNOWN,\n"
            "                       S.PARTIALLY_FILLED, S.CANCEL_PENDING})\n"
        ),
        replacement=(
            "IN_FLIGHT = frozenset({S.SEND_PENDING, S.ACKNOWLEDGED,\n"
            "                       S.PARTIALLY_FILLED, S.CANCEL_PENDING})\n"
        ),
        test=(
            "tests/sentinel/test_generated_economic_sequences.py::"
            "test_unknown_command_blocks_overlap_after_database_restart"
        ),
    ),
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _apply_once(path: Path, original: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(original)
    if count != 1:
        raise RuntimeError(
            f"{path}: mutation anchor occurs {count} times, expected exactly 1")
    path.write_text(text.replace(original, replacement), encoding="utf-8")


def _run(mutant: Mutant) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"sentinel-mutant-{mutant.name}-") as raw:
        overlay = Path(raw)
        shutil.copytree(RUNTIME / "sentinel", overlay / "sentinel")
        shutil.copytree(TEST_SOURCE / "tests", overlay / "tests")
        if (TEST_SOURCE / "docs").is_dir():
            (overlay / "docs").symlink_to(TEST_SOURCE / "docs",
                                           target_is_directory=True)
        source = overlay / mutant.relative_path
        before = _hash(source)
        _apply_once(source, mutant.original, mutant.replacement)
        after = _hash(source)

        env = dict(os.environ)
        inherited = [
            str(Path(value).resolve())
            for value in env.get("PYTHONPATH", "").split(os.pathsep)
            if value
        ]
        shared = REPO / "shared"
        env["PYTHONPATH"] = os.pathsep.join(
            [str(overlay)]
            + ([str(shared)] if shared.is_dir() else [])
            + inherited)
        relative_test, *selectors = mutant.test.split("::")
        test = "::".join((str(overlay / relative_test), *selectors))
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", test, "-q", "-ra"],
            cwd=overlay,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output = (completed.stdout + completed.stderr)[-12000:]
        killed = completed.returncode == 1 and " failed" in output
        return {
            "name": mutant.name,
            "source": mutant.relative_path,
            "source_sha256": before,
            "mutant_sha256": after,
            "test": mutant.test,
            "pytest_exit_code": completed.returncode,
            "mutant_killed": killed,
            "output_tail": output,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    records = []
    for mutant in MUTANTS:
        try:
            records.append(_run(mutant))
        except Exception as exc:  # noqa: BLE001
            records.append({
                "name": mutant.name,
                "source": mutant.relative_path,
                "test": mutant.test,
                "mutant_killed": False,
                "harness_error": f"{type(exc).__name__}: {exc}",
            })

    evidence = {
        "schema": "sentinel.mutation-certification/1",
        "tested_sha": os.environ.get("TESTED_SHA", "unknown"),
        "runtime_root": str(RUNTIME),
        "mutants": records,
        "all_mutants_killed": all(
            record.get("mutant_killed") is True for record in records),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "all_mutants_killed": evidence["all_mutants_killed"],
        "mutants": [
            {"name": record["name"],
             "mutant_killed": record.get("mutant_killed", False)}
            for record in records
        ],
    }, sort_keys=True))
    return 0 if evidence["all_mutants_killed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
