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
