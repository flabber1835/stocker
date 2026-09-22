"""Verify retained mechanical results against independently pinned anchors."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from research.economic_diagnosis.phases import OWNED, PARAMETERS


def main():
    root = Path("audit/economic-diagnosis")
    result = json.loads((root/"phase-summary.json").read_text())
    for key, expected in (("current_controller_parity_closes", 3760),
                          ("canonical_restart_pairs", 224),
                          ("controller_and_account_restart_pairs_each", 1344)):
        assert result["checks"][key] == expected, key
    anchors = {}
    pairs = 0
    for commit, name, profiles in (
        (PARAMETERS, "audit/parameter-probes/summary.json", ("current", "fast_sensitive", "slow_earlier", "recovery_faster", "combined")),
        (OWNED, "audit/owned-impairment/summary.json", ("current", "owned"))):
        raw = subprocess.check_output(["git", "show", f"{commit}:{name}"])
        anchors[f"{commit}:{name}"] = hashlib.sha256(raw).hexdigest()
        reference = json.loads(raw)
        for case, data in result["phases"]["80"].items():
            for profile in profiles:
                for key in ("ending_nav", "max_drawdown", "fees", "turnover"):
                    assert data[profile][key] == reference[case][profile][key], (case, profile, key)
                    pairs += 1
    for phase in (40, 80, 120, 160):
        data = json.loads(gzip.decompress((root/f"phase-{phase}.json.gz").read_bytes()))
        for case, experiment in data["cases"].items():
            assert experiment["summary"] == result["phases"][str(phase)][case]
            assert len(experiment["records"]) == 120
            for row in experiment["records"]:
                assert row["variants"]["current"]["decision"]["target"] == row["core_multiplier"]
    historical_pairs = 0
    for year, expected in ((2011, 12), (2018, 19), (2026, 70)):
        data = json.loads(gzip.decompress((root/f"window-{year}.json.gz").read_bytes()))
        assert data["exact_economic_and_decision_pairs"] == len(data["observations"]) == expected
        historical_pairs += expected
    accounting = json.loads((root/"summary.json").read_text())
    assert accounting["measured_sessions"] == 5032
    assert max(accounting["diagonal_max_relative_error"].values()) < 1e-9
    out = dict(verdict="PASS", prior_economic_comparisons=pairs,
               historical_exact_pairs=historical_pairs, source_anchors=anchors)
    (root/"verification.json").write_text(json.dumps(out, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
