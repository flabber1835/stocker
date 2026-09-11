#!/usr/bin/env python3
"""Falsify compact champion recovery and restart guards in memory."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _pytest.outcomes import Failed
from sentinel.controller import champion, champion_frozen
from tests.champion import test_authority, test_controller
from tools.median5_mutation_check import rewritten


def run():
    recovery = test_controller.test_rec8_requires_eight_sessions_and_strict_r40_recovery
    cases = (
        ("rec7_releases_champion", recovery, champion_frozen, "LDRC_REC", 7),
        ("r40_equality_releases_champion", recovery, champion_frozen.CandidateA, "step",
         rewritten(champion_frozen.CandidateA.step,
                   "recent_r40 > -0.04", "recent_r40 >= -0.04")),
        ("restart_accepts_ramp_history",
         lambda: test_authority.test_restart_rejects_incompatible_compact_native_memory(
             "ramp_entry_session", "2006-01-03"),
         champion, "validate_native", rewritten(champion.validate_native,
             'or before["ramp_entry_session"] is not None', "or False")),
        ("restart_accepts_unbounded_recovery_counter",
         lambda: test_authority.test_restart_rejects_corrupted_or_previous_recovery_memory("counter"),
         champion, "validate_recovery", rewritten(champion.validate_recovery,
             "not 0 <= state[field] <= 8", "state[field] < 0")),
    )
    results = []
    for name, falsifier, owner, attribute, mutant in cases:
        falsifier()
        with patch.object(owner, attribute, mutant):
            try:
                falsifier()
            except (AssertionError, Failed):
                results.append({"mutation": name, "status": "KILLED"})
            else:
                raise AssertionError("SURVIVED: " + name)
    return {"status": "PASS", "mutations": results}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
