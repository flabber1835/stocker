"""Focused reversible mutations; run against a private checkout, never a worker."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OWNED = 'sentinel/controller/owned_impairment.py'
TEST = 'tests/champion/test_owned_impairment.py::'
FORM = 'tests/sentinel/test_historical_formation.py::'
CASES = [
    ('wrong_ceiling', OWNED, 'active_ceiling=.55)', 'active_ceiling=0.)',
     TEST+'test_saturated_damage_enters_on_fifth_close_without_new_shock'),
    ('early_entry', OWNED, 'entry_sessions=5', 'entry_sessions=4',
     TEST+'test_saturated_damage_enters_on_fifth_close_without_new_shock'),
    ('early_release', OWNED, 'recovery_sessions=8', 'recovery_sessions=7',
     TEST+'test_recovery_needs_eight_owned_healthy_closes_and_preserves_parent_ceiling'),
    ('lost_parent_zero', OWNED, 'min(base_target, ceiling)', 'ceiling',
     TEST+'test_owned_ceiling_preserves_independent_parent_defense[0.0-0.0]'),
    ('duplicate_session', OWNED, 'session <= before.last_session', 'False',
     TEST+'test_duplicate_or_older_session_is_rejected_without_mutation'),
    ('detached_source', 'sentinel/core/formation.py',
     "or value['plan'] != plan.model_dump(by_alias=True)", 'or False',
     FORM+'test_resume_cannot_rebase_capital_or_change_source_period[change1]'),
    ('disconnected_ceiling', 'sentinel/core/kernel.py',
     '"target_core_exposure": owned_evidence["target"]',
     '"target_core_exposure": decision["target_core_exposure"]',
     FORM+'test_active_owned_cause_reaches_final_kernel_target'),
    ('sector_dependency', 'sentinel/core/kernel.py',
     'breadth, held = peer_breadth(state, feed, median5_state["spy_history"], median5_state["peer_keys"])',
     'pass  # mutant retains the legacy sector breadth',
     FORM+'test_current_controller_uses_correlation_peers_not_sector_labels'),
]


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT/'shared'))),
               PYTHONDONTWRITEBYTECODE='1')
    for name, filename, old, new, node in CASES:
        path = ROOT/filename
        original = path.read_bytes()
        if original.count(old.encode()) != 1:
            raise ValueError('mutation anchor changed: '+name)
        command = [sys.executable, '-B', '-m', 'pytest', node, '-q', '--tb=short', '-p', 'no:cacheprovider']
        try:
            path.write_bytes(original.replace(old.encode(), new.encode()))
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
        finally:
            path.write_bytes(original)
        log = result.stdout + result.stderr
        (output/(name+'.log')).write_text(log, encoding='utf-8')
        killed = result.returncode == 1 and 'FAILED ' in log and 'ERROR ' not in log
        results.append(dict(name=name, killed=killed, returncode=result.returncode, command=command))
        print(name, 'KILLED' if killed else 'UNPROVEN', flush=True)
        if path.read_bytes() != original:
            raise ValueError('restoration failed')
    (output/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return 0 if all(r['killed'] for r in results) else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(parser.parse_args().output))
