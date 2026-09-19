"""Remove each finite-timing guard and require startup rejection to fail."""
from tools.sentinel_rolling_storage_falsifiers import main


MUTANTS = {
    'shadow_deadline': (
        'sentinel.shadow_supervisor', 'not math.isfinite(deadline_seconds) or ', '',
        'test_shadow_refuses_invalid_deadline_before_worker[nan]'),
    'automation_poll': (
        'sentinel.automation_supervisor', 'not math.isfinite(poll_seconds) or ', '',
        'test_automation_refuses_invalid_timing_before_worker[inf-POLL]'),
    'automation_startup_grace': (
        'sentinel.automation_supervisor', 'not math.isfinite(startup_grace_seconds)', 'False',
        'test_automation_refuses_invalid_timing_before_worker[nan-STARTUP_GRACE]'),
}


if __name__ == '__main__':
    raise SystemExit(main(mutants=MUTANTS,
                         test_file='tests/sentinel/test_supervisor_timing_admission.py',
                         runner='tools.sentinel_supervisor_timing_falsifiers'))
