from __future__ import annotations

import csv
from datetime import date, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from backtester import canonical_pit_dataset as cpd


ROOT = Path(__file__).resolve().parents[2]


def _business_sessions(count: int) -> list[str]:
    result: list[str] = []
    current = date(2006, 1, 3)
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _write_gzip_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


def _descriptor(path: Path, rows: int) -> dict[str, object]:
    return {
        "sha256": cpd.sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": rows,
    }


def _build_v2_fixture(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    sessions = _business_sessions(170)
    first = sessions[0]
    securities = [(str(1000 + index), f"S{index:02d}") for index in range(12)]

    observations: list[dict[str, object]] = []
    for day_index, session in enumerate(sessions):
        for security_index, (sid, ticker) in enumerate(securities):
            base = 20.0 + security_index
            trend = 0.00025 * (security_index + 1)
            close = base * (1.0 + trend * day_index)
            observations.append({
                "session": session,
                "security_id": sid,
                "ticker": ticker,
                "issuer_id": f"SEC_CIK:{900000 + security_index}",
                "issuer_source": "TEST_STRICT_PRIOR_SEC",
                "security_type": "common",
                "security_type_source": "TEST_CAUSAL_COMMON",
                "security_type_eligible": "1",
                "sic": "3571",
                "ff12": "BusEq",
                "sector_source": "TEST_STRICT_PRIOR_SIC",
                "listing_active": "1",
                "listing_first_session": first,
                "exchange": "",
                "exchange_authoritative": "0",
                "raw_open": f"{close * 0.999:.12f}",
                "raw_close": f"{close:.12f}",
                "signal_close": f"{close:.12f}",
                "reported_volume": "20000000",
                "raw_compatible_volume": "20000000",
                "split_ratio": "1",
                "dividend_per_share": "0",
                "tradeable": "1",
                "metadata_admitted": "1",
                "identity_source": "SEP_TAPE_CONTINUITY_CAUSAL_TERMINAL_RELISTING_V1",
            })
    observation_path = root / "observations-2006.csv.gz"
    _write_gzip_csv(observation_path, cpd.OBSERVATION_COLUMNS, observations)

    metadata = []
    for security_index, (sid, ticker) in enumerate(securities):
        metadata.append({
            "effective_session": first,
            "security_id": sid,
            "ticker": ticker,
            "issuer_id": f"SEC_CIK:{900000 + security_index}",
            "issuer_source": "TEST_STRICT_PRIOR_SEC",
            "security_type": "common",
            "security_type_source": "TEST_CAUSAL_COMMON",
            "security_type_eligible": "1",
            "sic": "3571",
            "ff12": "BusEq",
            "sector_source": "TEST_STRICT_PRIOR_SIC",
            "listing_first_session": first,
            "metadata_admitted": "1",
        })
    metadata_path = root / "metadata-timeline.csv.gz"
    _write_gzip_csv(metadata_path, cpd.METADATA_COLUMNS, metadata)

    actions_path = root / "actions.csv.gz"
    terminals_path = root / "terminal-events.csv.gz"
    _write_gzip_csv(actions_path, cpd.ACTION_COLUMNS, [])
    _write_gzip_csv(terminals_path, cpd.TERMINAL_COLUMNS, [])

    cash_rows = [{
        "session": session,
        "gap_factor": "1",
        "intraday_factor": "1",
        "close_to_close_factor": "1",
        "source": "BIL",
    } for session in sessions]
    cash_path = root / "cash.csv.gz"
    _write_gzip_csv(cash_path, cpd.CASH_COLUMNS, cash_rows)

    benchmark_rows = []
    level = 1.0
    for index, session in enumerate(sessions):
        factor = 1.0 if index == 0 else 1.0002
        if index:
            level *= factor
        benchmark_rows.append({
            "session": session,
            "ticker": "SPY",
            "close_to_close_factor": f"{factor:.12f}",
            "level": f"{level:.12f}",
        })
    benchmark_path = root / "benchmark.csv.gz"
    _write_gzip_csv(benchmark_path, cpd.BENCHMARK_COLUMNS, benchmark_rows)

    session_hash_rows = [{
        "session": session,
        "observation_rows": len(securities),
        "action_rows": 0,
        "terminal_rows": 0,
        "input_sha256": hashlib.sha256(("fixture|" + session).encode()).hexdigest(),
    } for session in sessions]
    session_hash_path = root / "session-hashes.csv"
    _write_csv(session_hash_path, cpd.SESSION_HASH_COLUMNS, session_hash_rows)

    members = {
        observation_path.name: _descriptor(observation_path, len(observations)),
        metadata_path.name: _descriptor(metadata_path, len(metadata)),
        actions_path.name: _descriptor(actions_path, 0),
        terminals_path.name: _descriptor(terminals_path, 0),
        cash_path.name: _descriptor(cash_path, len(cash_rows)),
        benchmark_path.name: _descriptor(benchmark_path, len(benchmark_rows)),
        session_hash_path.name: _descriptor(session_hash_path, len(session_hash_rows)),
    }
    dataset_hash = cpd._dataset_hash(members)
    manifest = {
        "schema": cpd.SCHEMA,
        "dataset_id": "future-leak-real-kernel-fixture",
        "status": "PASS",
        "dataset_hash": dataset_hash,
        "reconstruction_code_sha": "3" * 40,
        "window": {
            "warmup_start": sessions[0],
            "measurement_start": sessions[0],
            "end": sessions[-1],
        },
        "counts": {
            "observation_rows": len(observations),
            "security_count": len(securities),
            "session_count": len(sessions),
            "metadata_timeline_rows": len(metadata),
            "action_rows": 0,
            "terminal_rows": 0,
            "incomplete_terminal_terms": 0,
            "unresolved_corporate_actions": 0,
            "unknown_security_type_observations": 0,
            "unknown_issuer_securities_at_end": 0,
        },
        "blockers": {"unresolved_corporate_actions": []},
        "identity_audit": {"blocking_identity_conflicts": 0},
        "causal_metadata_audit": {
            "metadata_after_decision_consumptions": 0,
            "future_metadata_authority_violations": 0,
        },
        "members": dict(sorted(members.items())),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class RealKernelFutureLeakCanaryTests(unittest.TestCase):
    def test_hash_valid_v2_fixture_executes_real_production_kernel_canary(self) -> None:
        main_src = ROOT / "main-src"
        if not (main_src / "sentinel" / "core" / "kernel.py").is_file():
            self.skipTest("pinned main-src runtime is not materialized")
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "canonical"
            _build_v2_fixture(dataset)
            script = (
                "import json,sys; from pathlib import Path; "
                "from backtester.future_leak_certification import run_real_replay_interface; "
                "r=run_real_replay_interface(Path(sys.argv[1])); "
                "print('REAL_CANARY_RESULT='+json.dumps(r,sort_keys=True))"
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join([
                str(main_src), str(main_src / "shared"), str(ROOT)
            ])
            completed = subprocess.run(
                [sys.executable, "-c", script, str(dataset)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"stdout={completed.stdout}\nstderr={completed.stderr}",
            )
            marker = next(
                (line for line in completed.stdout.splitlines()
                 if line.startswith("REAL_CANARY_RESULT=")),
                None,
            )
            self.assertIsNotNone(
                marker,
                f"real canary result missing; stdout={completed.stdout}\nstderr={completed.stderr}",
            )
            result = json.loads(marker.split("=", 1)[1])
            self.assertEqual(result.get("status"), "PASS", result)
            self.assertEqual(result.get("years"), [2006], result)
            self.assertTrue(result.get("cutoffs"), result)
            self.assertTrue(
                all(row.get("negative_control_detected") for row in result["cutoffs"]),
                result,
            )
            self.assertTrue(
                all(not row.get("pre_cutoff_mismatches") for row in result["cutoffs"]),
                result,
            )


if __name__ == "__main__":
    unittest.main()
