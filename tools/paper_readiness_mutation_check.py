#!/usr/bin/env python3
"""Prove forward-paper guards against intentional in-memory/source-copy defects."""
import argparse
import importlib
import inspect
from pathlib import Path
import sys
import textwrap
from types import FunctionType
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests" / "backup")]
PAPER = "tests/sentinel/test_paper_reporting_continuity.py::"
SUPERVISOR = "tests/sentinel/test_supervisor_dependency_bounds.py::"
BACKUP = "tests/backup/test_maintenance.py::"
CASES = {
    "reporting-gap": ("sentinel.paper_performance", "scan_entitlements",
        "if informational_only:", "if False:",
        PAPER + "test_missing_native_rows_are_reported_without_inventing_cash_or_fills"),
    "partial-notional": ("sentinel.execution.fill_integrity", "require_durable_coverage",
        "or Fraction(gross) >= Fraction(quantity) * Fraction(average)", "or False",
        PAPER + "test_contradictory_native_economics_still_refuse_informational_mode"),
    "all-commands": ("sentinel.execution.fill_integrity", "require_durable_coverage",
        "complete = False\n                continue", "return False",
        PAPER + "test_incomplete_first_command_cannot_hide_later_contradiction"),
    "unresolved-command": ("sentinel.execution.fill_integrity", "require_durable_coverage",
        "if CommandState(state) in IN_FLIGHT:", "if False:",
        PAPER + "test_unresolved_commands_remain_a_refusal"),
    "historical-finalization": ("sentinel.paper.preparation", "prepare_paper_plan",
        "if due_existing_cycle and not dual_mode:", "if due_existing_cycle:",
        "tests/sentinel/test_rolling_paper_inputs.py::"
        "test_real_paper_preparation_and_restart_reuse_only_verified_rolling_shadow[alpaca-True]"),
    "heartbeat-bound": ("sentinel.shadow_supervisor", "_touch",
        "supervisor_io.run(_touch_file)", "_touch_file()",
        SUPERVISOR + "test_filesystem_heartbeat_stall_cannot_hold_the_worker_deadline"),
    "health-bound": ("sentinel.shadow_supervisor", "_health",
        "supervisor_io.run(_health_snapshot, max_age_seconds, config, timeout=3)",
        "_health_snapshot(max_age_seconds, config)",
        SUPERVISOR + "test_entire_shadow_health_read_is_bounded"),
    "holder-bound": ("sentinel.automation_supervisor", "_spawn",
        "supervisor_io.run(_write_holder, holder_id)", "_write_holder(holder_id)",
        SUPERVISOR + "test_holder_file_stall_refuses_before_starting_worker"),
    "observer-replacement": ("sentinel.supervisor_io", "run",
        "for prior in list(_UNREAPED):", "for prior in []:",
        SUPERVISOR + "test_unreaped_dependency_prevents_replacement"),
    "unknown-latch": ("sentinel.shadow_supervisor", "run",
        "latched = supervisor_io.run(_latch_exists)", "latched = False",
        SUPERVISOR + "test_unknown_shadow_latch_cannot_start_worker"),
    "worker-arm": ("sentinel.shadow_supervisor", "run",
        "supervisor_io.run(_arm_worker, timeout=2)", "pass",
        SUPERVISOR + "test_terminal_refusal_survives_latch_timeout_and_restart"),
    "pending-health": ("sentinel.shadow_supervisor", "_latch_exists",
        " or _pending_file().exists()", "",
        SUPERVISOR + "test_terminal_refusal_survives_latch_timeout_and_restart"),
    "latch-timeout": ("sentinel.shadow_supervisor", "_latch",
        "pending = _try_persist_latch(payload)",
        "supervisor_io.run(_persist_latch, payload, timeout=2); pending = None",
        SUPERVISOR + "test_terminal_refusal_survives_latch_timeout_and_restart"),
    "backup-age": ("sentinel_backup_maintenance", "renewal_due",
        "age >= RENEW_SECONDS", "False",
        "tests/backup/test_recurring_maintenance.py::test_production_tick_renews_verifies_restores_then_retains_and_restarts"),
    "backup-wal": ("sentinel_backup_maintenance", "renewal_due",
        "footprint >= RENEW_BYTES", "False",
        "tests/backup/test_recurring_maintenance.py::test_proactive_wal_boundary_is_independent_of_age"),
    "backup-group": ("sentinel_maintenance_process", "run_bounded",
        "os.killpg(process.pid, signal.SIGKILL)", "process.kill()",
        BACKUP + "test_timeout_kills_descendant_before_late_write"),
    "backup-deadline": ("sentinel_maintenance_process", "run_bounded",
        "if remaining <= 0:", "if False:",
        BACKUP + "test_timeout_kills_descendant_before_late_write"),
    "backup-output": ("sentinel_maintenance_process", "run_bounded",
        "elif len(output) + len(errors) + len(chunk) > MAX_OUTPUT:", "elif False:",
        BACKUP + "test_output_is_bounded"),
    "backup-log": ("sentinel_maintenance_process", "emit_result",
        'child.communicate(json.dumps([result.stdout, result.stderr]).encode("utf-8"), timeout=1)',
        'child.communicate(json.dumps([result.stdout, result.stderr]).encode("utf-8"))',
        BACKUP + "test_full_scheduler_log_cannot_block_completion"),
    "exact-backup": ("sentinel_backup_maintenance", "tick",
        'if paths[0] != root + "/base/" + selected["name"]:', 'if False:',
        "tests/backup/test_recurring_maintenance.py::test_successor_identity_mismatch_refuses_before_status_or_retention"),
}


def case(name):
    if name == "backup-selection":
        from sentinel import backup_retention as retention
        original = retention.Media.selected
        def discover(self):
            try:
                return original(self)
            except FileNotFoundError:
                name = max(p.name for p in self.base.iterdir() if p.is_dir())
                return retention.metadata(self.base, name, self.system_id)
        return retention.Media, 'selected', discover, (
            'tests/backup/test_recurring_maintenance.py::'
            'test_promoted_backup_without_runtime_selection_cannot_be_healthy')
    if name == "container-copy-lock":
        from test_shell_lifecycle import ShellLab
        original = ShellLab.__init__
        def unlocked(self, *args, **kwargs):
            original(self, *args, **kwargs)
            path = self.scripts / "sentinel-backup-media-lock.sh"
            source = path.read_text()
            assert source.count("flock -x -n 9 || return 4") == 1
            path.write_text(source.replace("flock -x -n 9 || return 4", ":"))
        return ShellLab, "__init__", unlocked, BACKUP + "test_orphaned_container_copy_fences_staging_cleanup"
    module_name, attribute, old, new, selection = CASES[name]
    module = importlib.import_module(module_name)
    source = textwrap.dedent(inspect.getsource(getattr(module, attribute)))
    assert source.count(old) == 1, "mutation seam disappeared"
    namespace = dict(module.__dict__)
    exec(compile(source.replace(old, new), module.__file__, "exec"), namespace)
    compiled = namespace[attribute]
    mutant = FunctionType(compiled.__code__, module.__dict__, attribute, compiled.__defaults__)
    mutant.__kwdefaults__ = compiled.__kwdefaults__
    owner = importlib.import_module("sentinel.paper") if name == "historical-finalization" else module
    return owner, attribute, mutant, selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mutation", choices=[*CASES, "container-copy-lock", "backup-selection"])
    name = parser.parse_args().mutation
    owner, attribute, mutant, selection = case(name)
    args = [selection, "-q", "--tb=short", "--show-capture=no", "-p", "no:cacheprovider"]
    if pytest.main(args) != pytest.ExitCode.OK:
        raise SystemExit("Unmodified acceptance must pass first")
    with patch.object(owner, attribute, mutant):
        result = pytest.main(args)
    if result != pytest.ExitCode.TESTS_FAILED:
        raise SystemExit(f"Mutation was not detected: {name} ({result})")
    print(f"MUTATION_RESULT {name}: KILLED")


if __name__ == "__main__":
    main()
