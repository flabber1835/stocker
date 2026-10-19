#!/usr/bin/env python3
"""Kill reviewed Sentinel mutants in disposable import overlays."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


REPO = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[1])).resolve()
RUNTIME = Path("/app") if Path("/app/sentinel").is_dir() else REPO
TEST_SOURCE = Path("/work") if Path("/work/tests").is_dir() else REPO


@dataclass(frozen=True)
class FailureSignal:
    exception: str
    message_pattern: str | None = None


ASSERTION_SIGNALS = (
    FailureSignal("builtins.AssertionError"),
    # Pytest intentionally publishes Failed as a builtins type. Accept only
    # its missing-exception assertion, not arbitrary pytest.fail() messages.
    FailureSignal("builtins.Failed", r"^DID NOT RAISE <class '[A-Za-z0-9_.]+'>$"),
)


@dataclass(frozen=True)
class Mutant:
    name: str
    relative_path: str
    original: str
    replacement: str
    test: str
    failure_signals: tuple[FailureSignal, ...] = ASSERTION_SIGNALS


MUTANTS = (
    Mutant(
        name="submit-before-send-pending",
        relative_path="sentinel/execution/executor.py",
        original=(
            "    pending = recovery.prepare_send(command)\n"
            "    journal.save_command(conn, pending, previous=command.state)\n\n"
            "    try:\n"
            "        settled = await recovery.dispatch(broker, pending)\n"
        ),
        replacement=(
            "    pending = recovery.prepare_send(command)\n\n"
            "    try:\n"
            "        settled = await recovery.dispatch(broker, pending)\n"
            "        journal.save_command(conn, pending, previous=command.state)\n"
        ),
        test=(
            "tests/sentinel/test_process_death_recovery.py::"
            "test_process_death_recovers_one_order_and_one_fill_without_duplication"
        ),
    ),
    Mutant(
        name="working-order-added-to-remaining-delta",
        relative_path="sentinel/execution/commands.py",
        original="    remaining = exact_decimal(Fraction(desired) - Fraction(held) - Fraction(committed))\n",
        replacement="    remaining = exact_decimal(Fraction(desired) - Fraction(held) + Fraction(committed))\n",
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
            '            "   AND snapshot_date<=%s AND " + visible_predicate("u", sep_retirements=False) +\n'
        ),
        replacement=(
            '            "  MAX(snapshot_date) snapshot_date"\n'
            '            " FROM sentinel_universe u"\n'
            '            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"\n'
            '            "   AND snapshot_date<%s AND " + visible_predicate("u", sep_retirements=False) +\n'
        ),
        test=(
            "tests/sentinel/test_issue209_session_effective_metadata.py::"
            "test_future_tickers_snapshot_cannot_change_missed_session"
        ),
        failure_signals=(FailureSignal(
            "sentinel.core.loader.CausalMetadataUnavailable",
            r"^no causally available TICKERS metadata exists on or before 2026-08-20$",
        ),),
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
        original="    residual = Fraction(nav) - invested\n",
        replacement="    residual = Fraction(nav) + invested\n",
        test=(
            "tests/sentinel/test_projection_and_executor.py::"
            "TestProjection::"
            "test_the_defensive_sleeve_absorbs_what_the_core_did_not_take"
        ),
    ),
    Mutant(
        name="alpaca-submit-falls-back-to-mutable-symbol",
        relative_path="sentinel/execution/alpaca.py",
        original='        body = _submit_body(symbol=str(instrument.broker_id), client_key=client_key,\n',
        replacement='        body = _submit_body(symbol=str(instrument.symbol), client_key=client_key,\n',
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


def _pytest_counts(junit: Path) -> dict[str, object]:
    counts: dict[str, object] = {
        "valid": False, "total": 0, "failures": 0, "errors": 0,
        "skipped": 0,
    }
    if not junit.exists():
        counts["parse_error"] = "JUnit report was not produced"
        return counts
    try:
        cases = list(ET.parse(junit).getroot().iter("testcase"))
    except (ET.ParseError, OSError) as exc:
        counts["parse_error"] = f"{type(exc).__name__}: {exc}"
        return counts
    counts.update(
        valid=True,
        total=len(cases),
        failures=sum(case.find("failure") is not None for case in cases),
        errors=sum(case.find("error") is not None for case in cases),
        skipped=sum(case.find("skipped") is not None for case in cases),
    )
    return counts


def _mutation_verdict(
    returncode: int, junit: Path, *, probe: dict | None = None,
    expected_cases: tuple[str, ...] = (),
    failure_signals: tuple[FailureSignal, ...] = ASSERTION_SIGNALS,
) -> tuple[bool, dict[str, object]]:
    """Require complete execution and an explicitly reviewed call failure."""
    counts = _pytest_counts(junit)
    calls = _complete_probe(probe, expected_cases)
    failures = [] if calls is None else [call for call in calls if call["exception"]]
    accepted = all(any(
        failure["exception"] == signal.exception
        and (signal.message_pattern is None
             or re.search(signal.message_pattern, failure["message"]) is not None)
        for signal in failure_signals) for failure in failures)
    killed = (
        returncode == 1
        and counts["valid"] is True
        and calls is not None
        and bool(failures)
        and accepted
        and int(counts["total"]) == len(expected_cases)
        and int(counts["failures"]) == len(failures)
        and int(counts["errors"]) == 0
        and int(counts["skipped"]) == 0
    )
    return killed, counts


def _complete_probe(probe: dict | None, expected: tuple[str, ...]) -> list[dict] | None:
    """Every expected case must execute each phase exactly once."""
    if (not expected or len(expected) != len(set(expected))
            or not isinstance(probe, dict) or probe.get("probe_error")
            or probe.get("collected") != list(expected)):
        return None
    reports = probe.get("reports")
    if not isinstance(reports, list) or len(reports) != 3 * len(expected):
        return None
    by_case = {case: {} for case in expected}
    for report in reports:
        if not isinstance(report, dict) or set(report) != {
                "nodeid", "phase", "exception", "message"}:
            return None
        case, phase = report["nodeid"], report["phase"]
        if (case not in by_case or phase not in {"setup", "call", "teardown"}
                or phase in by_case[case]
                or not isinstance(report["message"], str)
                or (report["exception"] is not None
                    and not isinstance(report["exception"], str))):
            return None
        by_case[case][phase] = report
    for phases in by_case.values():
        if (set(phases) != {"setup", "call", "teardown"}
                or phases["setup"]["exception"] is not None
                or phases["teardown"]["exception"] is not None):
            return None
    return [by_case[case]["call"] for case in expected]


def _probe(spec_path: Path) -> int:
    """Private fresh-process entry point; JUnit does not retain exception types."""
    import pytest

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    overlay = Path(spec["overlay"]).resolve()
    source = overlay / spec["source"]
    result = {"collected": [], "reports": [], "source": None}

    class Probe:
        def pytest_collection_finish(self, session):
            result["collected"] = [item.nodeid for item in session.items]

        def pytest_runtest_makereport(self, item, call):
            exc = call.excinfo
            result["reports"].append({
                "nodeid": item.nodeid, "phase": call.when,
                "exception": (f"{exc.type.__module__}.{exc.type.__qualname__}"
                              if exc is not None else None),
                "message": str(exc.value)[:4000] if exc is not None else "",
            })

    try:
        module_name = ".".join(Path(spec["source"]).with_suffix("").parts)
        module = importlib.import_module(module_name)
        loaded = Path(module.__file__).resolve()
        result["source"] = {"path": str(loaded), "sha256": _hash(loaded)}
        if loaded != source.resolve() or _hash(loaded) != spec["sha256"]:
            raise RuntimeError("pytest did not import the authenticated overlay source")
        args = [spec["test"], "-q", "-ra", "-p", "no:cacheprovider",
                f"--rootdir={overlay}", f"--confcutdir={overlay}",
                f"--junitxml={spec['junit']}"]
        if (overlay / "pytest.ini").is_file():
            args.extend(["-c", str(overlay / "pytest.ini")])
        return int(pytest.main(args, plugins=[Probe()]))
    except Exception as exc:  # noqa: BLE001 - evidence must explain harness refusal
        result["probe_error"] = f"{type(exc).__name__}: {exc}"
        return 2
    finally:
        Path(spec["output"]).write_text(json.dumps(result, indent=2) + "\n",
                                       encoding="utf-8")


def _execute(overlay: Path, mutant: Mutant, source_hash: str,
             env: dict[str, str], phase: str) -> dict:
    output = overlay / f"{phase}-probe.json"
    junit = overlay / f"{phase}-junit.xml"
    spec = overlay / f"{phase}-input.json"
    spec.write_text(json.dumps({
        "overlay": str(overlay), "source": mutant.relative_path,
        "sha256": source_hash, "test": mutant.test,
        "output": str(output), "junit": str(junit),
    }), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--probe", str(spec)],
        cwd=overlay, env=env, capture_output=True, text=True, timeout=180,
    )
    probe = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    # Do not let a substituted or incomplete probe authenticate a different file.
    if probe.get("source") != {"path": str((overlay / mutant.relative_path).resolve()),
                              "sha256": source_hash}:
        probe["probe_error"] = "overlay source identity was not established"
    return {"pytest_exit_code": completed.returncode,
            "pytest_counts": _pytest_counts(junit), "probe": probe,
            "output_tail": (completed.stdout + completed.stderr)[-12000:]}


def _run(mutant: Mutant) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"sentinel-mutant-{mutant.name}-") as raw:
        overlay = Path(raw)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(RUNTIME / "sentinel", overlay / "sentinel", ignore=ignore)
        shutil.copytree(TEST_SOURCE / "tests", overlay / "tests", ignore=ignore)
        if (TEST_SOURCE / "pytest.ini").is_file():
            shutil.copy2(TEST_SOURCE / "pytest.ini", overlay / "pytest.ini")
        if (TEST_SOURCE / "docs").is_dir():
            (overlay / "docs").symlink_to(TEST_SOURCE / "docs",
                                           target_is_directory=True)
        source = overlay / mutant.relative_path
        before = _hash(source)

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
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        baseline = _execute(overlay, mutant, before, env, "baseline")
        collected = baseline["probe"].get("collected", [])
        expected = tuple(collected) if isinstance(collected, list) else ()
        calls = _complete_probe(baseline["probe"], expected)
        counts = baseline["pytest_counts"]
        baseline_passed = (
            baseline["pytest_exit_code"] == 0 and calls is not None
            and all(call["exception"] is None for call in calls)
            and counts["valid"] is True and counts["total"] == len(expected)
            and counts["failures"] == counts["errors"] == counts["skipped"] == 0)
        record = {
            "name": mutant.name, "source": mutant.relative_path,
            "source_sha256": before, "test": mutant.test,
            "baseline": baseline, "baseline_passed": baseline_passed,
            "expected_cases": list(expected), "mutant_killed": False,
            "failure_signals": [
                {"exception": signal.exception, "message_pattern": signal.message_pattern}
                for signal in mutant.failure_signals],
        }
        if not baseline_passed:
            return {**record, "harness_error": "unmodified overlay baseline did not pass"}
        _apply_once(source, mutant.original, mutant.replacement)
        after = _hash(source)
        mutated = _execute(overlay, mutant, after, env, "mutation")
        killed, counts = _mutation_verdict(
            mutated["pytest_exit_code"], overlay / "mutation-junit.xml",
            probe=mutated["probe"], expected_cases=expected,
            failure_signals=mutant.failure_signals)
        return {
            **record,
            "mutant_sha256": after,
            "pytest_exit_code": mutated["pytest_exit_code"],
            "pytest_counts": counts,
            "probe": mutated["probe"],
            "mutant_killed": killed,
            "output_tail": mutated["output_tail"],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--probe", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe is not None:
        return _probe(args.probe)
    if args.output is None:
        parser.error("--output is required")

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
