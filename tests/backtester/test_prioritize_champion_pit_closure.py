import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backtester.prioritize_champion_pit_closure import build


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _workrow(sid, ticker, unknown=0, terminal=0, durable=0, recent=0, held=0):
    return {
        "security_id": sid, "ticker": ticker,
        "first_touch_session": "2020-01-01", "last_touch_session": "2020-01-03",
        "unknown_type_base_sessions": unknown,
        "durable_ranked_sessions": durable, "recent_leadership_sessions": recent,
        "pending_sessions": 0, "held_sessions": held,
        "incomplete_terminal_sessions": terminal, "best_durable_rank": "2" if durable else "",
        "potential_displacer": "True" if unknown else "False",
    }


def _fixture(tmp_path: Path):
    work = tmp_path / "work.csv"
    rows = [_workrow(str(i), f"T{i}") for i in range(6914)]
    rows[0].update(_workrow("0", "RANK", unknown=2, durable=1))
    for i in range(1, 1751):
        rows[i].update(_workrow(str(i), f"T{i}", unknown=1))
    for i in range(1405):
        rows[i]["incomplete_terminal_sessions"] = 1
    rows[0]["held_sessions"] = 5
    _write_csv(work, rows)

    ledger = tmp_path / "ledger.jsonl.gz"
    with gzip.open(ledger, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"session": "2020-01-02", "base_candidate_unknown": [str(i) for i in range(1751)]}) + "\n")
        handle.write(json.dumps({"session": "2020-01-03", "base_candidate_unknown": ["0"]}) + "\n")

    v4 = tmp_path / "v4"
    v4.mkdir()
    events = v4 / "v4_authorized_security_type_events.csv.gz"
    with gzip.open(events, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["security_id", "ticker", "usable_after", "classification", "cik", "accession", "origin"])
        writer.writeheader()
        writer.writerow({"security_id": "0", "ticker": "RANK", "usable_after": "2020-01-01", "classification": "common", "cik": "1", "accession": "A", "origin": "TEST"})
        writer.writerow({"security_id": "1", "ticker": "T1", "usable_after": "2020-01-02", "classification": "non_common", "cik": "2", "accession": "B", "origin": "TEST"})
    conflicts = v4 / "security_type_conflicts_v4.csv.gz"
    with gzip.open(conflicts, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["security_id", "usable_after", "values"])
        writer.writeheader()
        writer.writerow({"security_id": "1", "usable_after": "2020-01-02", "values": "common;non_common"})
    sums = v4 / "SHA256SUMS.txt"
    sums.write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in (events, conflicts)
    ))
    return work, ledger, v4


class ChampionPITClosurePriorityTests(unittest.TestCase):
    def test_strict_prior_allocation_and_conflict_rejection(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            work, ledger, v4 = _fixture(root)
            result = build(worklist=work, session_ledger=ledger, v4_root=v4,
                           output=root / "out", enforce_frozen_inputs=False)
            self.assertEqual(result["security_type"]["resolved_observations"], 2)
            self.assertEqual(result["security_type"]["status_counts"]["ELIGIBLE"], 1)
            self.assertEqual(result["security_type"]["status_counts"]["UNRESOLVED"], 1750)
            self.assertEqual(result["security_type"]["rejected_conflicted_authority_rows"], 1)

    def test_priority_places_ranked_and_held_terminal_first(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            work, ledger, v4 = _fixture(root)
            build(worklist=work, session_ledger=ledger, v4_root=v4,
                  output=root / "out", enforce_frozen_inputs=False)
            with (root / "out/security-type-priority.csv").open() as handle:
                first = next(csv.DictReader(handle))
            self.assertEqual(first["security_id"], "0")
            self.assertEqual(first["priority"], "1_REACHED_RANK_OR_LEADERSHIP")
            with (root / "out/terminal-priority.csv").open() as handle:
                first_terminal = next(csv.DictReader(handle))
            self.assertEqual(first_terminal["security_id"], "0")
            self.assertEqual(first_terminal["priority"], "1_HELD_POSITION")


if __name__ == "__main__":
    unittest.main()
