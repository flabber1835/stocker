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
STARTUP_CASES = [
    ('go_legacy_frontier', 'tools/production_go_e2e_harness.py',
     'held.window_end if rolling_go_inputs.is_rolling(held)',
     'store.latest_visible_session(c) if rolling_go_inputs.is_rolling(held)',
     'tests/production_composition/test_canonical_go_e2e_harness.py::test_publication_observer_reads_the_selected_generation[rolling-startup]'),
    ('go_disconnected_preparation_fault', 'tools/production_go_stage_faults.py',
     '("sentinel.feed.rolling_go_inputs", "prepare")',
     '("sentinel.feed.outage_recovery", "catch_up")',
     'tests/production_composition/test_internal_go_stage_faults.py::test_rolling_fault_reaches_the_production_call_site[feed-catchup-prepare]'),
    ('go_disconnected_readiness_fault', 'tools/production_go_stage_faults.py',
     'fault, "sentinel.feed.rolling_go_inputs", "readiness"',
     'fault, "sentinel.feed.readiness", "check_readiness"',
     'tests/production_composition/test_internal_go_stage_faults.py::test_rolling_fault_reaches_the_production_call_site[sharadar-readiness-readiness]'),
    ('go_false_sensitivity_claim', 'tools/production_go_e2e_audit.py',
     'if sensitivity_group == "positive" and sensitivity:', 'if False:',
     'tests/production_composition/test_internal_go_stage_faults.py::test_positive_campaign_cannot_claim_sensitivity'),
    ('unsigned_formed_origin', 'sentinel/formed_origin.py',
     "or not hmac.compare_digest(str(value['hmac_sha256']), _signature(payload))", 'or False',
     'tests/sentinel/test_formed_startup.py::test_authenticated_origin_cannot_change_context_or_seed'),
    ('unsigned_progress', 'sentinel/formation_bootstrap.py',
     "or not hmac.compare_digest(str(value['hmac_sha256']), _signature(checkpoint, context))", 'or False',
     'tests/sentinel/test_formed_startup.py::test_progress_cannot_be_self_rehashed_or_rebound[rehashed_state]'),
    ('disconnected_formation', 'sentinel/rolling_initialization.py',
     "if owned(context['strategy']):", 'if False:',
     'tests/sentinel/test_rolling_initialization.py::test_real_publication_forms_historical_book_and_atomic_checkpoint'),
    ('free_stock_entry', 'sentinel/formed_economics.py',
     "cost = D('.001') * turnover", "cost = D('.001') * (1-allocation)",
     'tests/sentinel/test_formed_economics.py::test_flat_half_cash_book_pays_for_stock_and_bil_only[1-.9995]'),
    ('double_rotation_fee', 'sentinel/formed_economics.py',
     '(parent_close + fees) / parent_open - 1', 'parent_close / parent_open - 1',
     'tests/sentinel/test_formed_economics.py::test_canonical_rotation_cost_is_replaced_by_one_funded_entry'),
    ('formation_health_timeout', 'scripts/sentinel_autonomous_deploy.py',
     'env.get("SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS", "7200")',
     'env.get("SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS", "300")',
     'tests/sentinel/test_autonomous_deploy.py::test_real_config_allows_measured_formation_and_full_status_read'),
    ('status_short_timeout', 'scripts/sentinel_autonomous_deploy.py',
     'timeout=min(300, max(0.001, deadline - time.monotonic()))',
     'timeout=min(30, max(0.001, deadline - time.monotonic()))',
     'tests/sentinel/test_autonomous_deploy.py::test_real_config_allows_measured_formation_and_full_status_read'),
    ('late_status_acceptance', 'scripts/sentinel_autonomous_deploy.py',
     'if time.monotonic() >= deadline:\n                break\n            if completed.returncode',
     'if False:\n                break\n            if completed.returncode',
     'tests/sentinel/test_autonomous_deploy.py::test_shadow_read_cannot_authorize_after_data_deadline'),
    ('formation_spy_domain', 'sentinel/core/formation_inputs.py',
     'spy_closeadj=tuple(b.spy_total_return for b in benchmarks)',
     'spy_closeadj=tuple(b.bil_close_adjusted for b in benchmarks)',
     'tests/sentinel/test_rolling_initialization.py::test_composed_input_keeps_spy_equity_and_bil_domains_separate[formed]'),
    ('formation_bil_domain', 'sentinel/core/formation_inputs.py',
     'b.bil_close_signal, b.bil_close_adjusted, b.bil_close_unadjusted)',
     'b.bil_close_signal, b.bil_close_unadjusted, b.bil_close_adjusted)',
     'tests/sentinel/test_rolling_initialization.py::test_composed_input_keeps_spy_equity_and_bil_domains_separate[formed]'),
]


def main(output, group='controller', case=None):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT/'shared'))),
               PYTHONDONTWRITEBYTECODE='1')
    selected = STARTUP_CASES if group == 'startup' else CASES
    if case is not None:
        selected = [item for item in selected if item[0] == case]
        if not selected:
            raise ValueError('unknown mutation: '+case)
    for name, filename, old, new, node in selected:
        path = ROOT/filename
        original = path.read_bytes()
        if original.count(old.encode()) != 1:
            raise ValueError('mutation anchor changed: '+name)
        command = [sys.executable, '-B', '-m', 'pytest', node, '-q', '--tb=short', '-p', 'no:cacheprovider']
        baseline = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
        (output/(name+'.baseline.log')).write_text(baseline.stdout + baseline.stderr, encoding='utf-8')
        if baseline.returncode != 0:
            raise ValueError('unmodified acceptance test must pass before mutation: '+name)
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
    parser.add_argument('--group', choices=['controller', 'startup'], default='controller')
    parser.add_argument('--case')
    args = parser.parse_args()
    raise SystemExit(main(args.output, args.group, args.case))
