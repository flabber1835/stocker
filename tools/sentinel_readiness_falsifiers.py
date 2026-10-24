"""Break readiness/notification guards only inside a disposable source copy."""
import argparse
from pathlib import Path
import subprocess
import sys

HOST='scripts/sentinel_activation_checkpoint.py'
MAINT='scripts/sentinel_backup_maintenance.py'
TEST='tests/backup/test_activation_checkpoint.py::'
MUTANTS={
    'exact_runtime':(MAINT,'and result["runtime_image"] == image','and True',
        TEST+'test_ineligible_receipt_cannot_reuse_or_write_marker[runtime_image-sha256:'+ 'e'*64+']'),
    'full_receipt':(MAINT,'for k, v in expected.items()):','for k, v in expected.items() if k != "physical_only"):',
        TEST+'test_ineligible_receipt_cannot_reuse_or_write_marker[physical_only-True]'),
    'selected_metadata':(HOST,'current != selected or ','False or ',TEST+'test_selected_metadata_change_refuses'),
    'committed_flush':(HOST,"if _lsn(barrier.get('lsn')) < _lsn(before['lsn']):",'if False:',
        TEST+'test_barrier_mismatch_refuses_without_success_or_new_copy[lsn-0/E000001]'),
    'archive_coverage':(HOST,'if require_coverage(proof, barrier, after, allow_pending=True):','if True:',
        TEST+'test_delayed_archive_has_one_fixed_budget_and_never_publishes_prematurely'),
    'original_deadline':(HOST,'ARCHIVE_SECONDS = 60','ARCHIVE_SECONDS = 61',
        TEST+'test_delayed_archive_has_one_fixed_budget_and_never_publishes_prematurely'),
    'planned_info_delivery':('sentinel/web_push.py','"PUSH_ENROLLMENT_TEST", "PAPER_PLAN_READY",',
        '"PUSH_ENROLLMENT_TEST",',
        'tests/sentinel/test_paper_plan_notifications.py::test_ordinary_info_stays_quiet_and_plan_info_reaches_existing_push_pipeline'),
    'notification_expiry':('sentinel/web_push.py','if datetime.now(timezone.utc) >= execute_at:','if False:',
        'tests/sentinel/test_paper_plan_notifications.py::test_ordinary_info_stays_quiet_and_plan_info_reaches_existing_push_pipeline'),
    'fresh_clock':('sentinel/automation/service.py',
        'now=now, conn_factory=heartbeat_conn_factory, clock=clock)',
        'now=now, conn_factory=heartbeat_conn_factory, clock=None)',
        'tests/sentinel/test_automation_clock_sampling.py::test_control_read_delay_uses_fresh_host_sample_before_leadership'),
    'clock_precision':('sentinel/automation/service.py','if outer > limit:', 'if False:',
        'tests/sentinel/test_automation_clock_sampling.py::test_wide_sample_waits_even_when_database_is_between_safe_endpoints'),
    'real_clock_drift':('sentinel/automation/service.py','if skew > limit:', 'if False:',
        'tests/sentinel/test_automation_clock_sampling.py::test_fresh_sampler_still_refuses_real_drift[6]'),
    'clock_uncertainty':('sentinel/automation/service.py',
        'abs((after - database_now).total_seconds())) > limit:',
        'abs((after - database_now).total_seconds())) > float("inf"):',
        'tests/sentinel/test_automation_clock_sampling.py::test_ambiguous_interval_waits_without_widening_the_skew_limit[6]'),
    'duplicate_boundary':(HOST,'if key in value:', 'if False:',
        'tests/backup/test_activation_checkpoint.py::test_malformed_boundary_cannot_authorize_archive_checkpoint'),
    'duplicate_opening_slots':('sentinel/paper_plan_preview.py',
        "or item['slot_id'] in slots or targets.get(sid) != 0", 'or targets.get(sid) != 0',
        'tests/sentinel/test_paper_plan_preview.py::test_duplicate_opening_slots_cannot_announce_two_buys'),
    'obsolete_plan_delivery':('sentinel/web_push.py','if not current:', 'if False:',
        'tests/sentinel/test_paper_plan_notifications.py::test_queued_plan_is_revalidated_before_push_fanout[generation]'),
    'independent_critical_delivery':('sentinel/automation/outbox.py',
        'except (ValueError, TypeError, ArithmeticError):', 'except (RuntimeError,):',
        'tests/sentinel/test_paper_plan_notifications.py::test_unreadable_optional_plan_cannot_block_critical_alert_delivery[NaN]'),
    'poll_gap_after_slow_work':('sentinel/automation/service.py',
        '                now = _utc(clock())\n                wake_candidates = [',
        '                wake_candidates = [',
        'tests/sentinel/test_automation_clock_sampling.py::test_slow_tick_keeps_a_bounded_poll_gap_instead_of_a_busy_burst'),
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child',choices=MUTANTS)
    args=parser.parse_args()
    if Path.cwd().resolve()!=Path('/tmp/repo') or not Path('/source').is_dir():
        raise RuntimeError('readiness mutations require an isolated disposable source runner')
    if args.child:
        import pytest
        name,old,new,test=MUTANTS[args.child]
        path=Path(name);raw=path.read_bytes();source=raw.decode()
        assert source.count(old)==1,(name,old)
        try:
            path.write_bytes(source.replace(old,new,1).encode())
            return pytest.main([test,'-q','--tb=short','-p','no:cacheprovider'])
        finally:path.write_bytes(raw)
    failed=[]
    for name in MUTANTS:
        value=subprocess.run([sys.executable,'-m',__spec__.name,'--child',name],
            capture_output=True,text=True,timeout=30)
        killed=value.returncode==1 and '1 failed' in value.stdout
        print(name+(': KILLED' if killed else ': NOT PROVED'),flush=True)
        if not killed:
            failed.append(name);print(value.stdout[-2500:]+value.stderr[-1000:])
    return bool(failed)


if __name__=='__main__':raise SystemExit(main())
