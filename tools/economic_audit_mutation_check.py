"""Run a passing acceptance case, then require its in-memory mutant to fail."""
from __future__ import annotations

import argparse
import inspect
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def case(name):
    if name == 'push-serialization':
        from sentinel import push_recipients
        return (push_recipients, 'lock', lambda cur: None,
                'tests/sentinel/test_notification_recovery.py::test_rotation_cannot_cross_delivery_result_transaction')
    if name in {'stream-deadline', 'stream-group', 'push-successor', 'push-eligibility', 'push-revision', 'push-capture', 'push-conflict', 'push-incarnation', 'push-removal', 'push-chain-interval'}:
        import importlib
        import textwrap
        import types
        if name.startswith('stream-'):
            module = importlib.import_module('tests.sentinel.test_autonomous_deploy').deploy
            owner, attribute = module.Runner, '_stream'
            old, new, selection = {
                'stream-deadline': ('deadline = None if timeout is None else time.monotonic() + timeout', 'deadline = None', 'test_streaming_deadline_covers_silent_partial_closed_and_inherited_pipe'),
                'stream-group': ('os.killpg(process.pid, signal.SIGKILL)', 'pass', 'test_stream_timeout_kills_descendant_before_its_late_side_effect'),
            }[name]
            selection = 'tests/sentinel/test_autonomous_deploy.py::' + selection
        else:
            module = importlib.import_module('sentinel.panel.push_enrollment' if name in {'push-conflict', 'push-incarnation', 'push-removal'} else 'sentinel.push_recipients' if name in {'push-successor', 'push-eligibility', 'push-chain-interval'} else 'sentinel.web_push')
            owner = module if name in {'push-successor', 'push-eligibility', 'push-conflict', 'push-incarnation', 'push-removal', 'push-chain-interval'} else module.WebPushAlertAdapter
            attribute, old, new, selection = {
                'push-successor': ('resolve', 'if successor is None:', 'if True:', 'test_pending_alert_follows_rotation_before_or_after_fanout'),
                'push-eligibility': ('resolve', 'if recipient.eligible_from > created_at:', 'if False:', 'test_explicit_removal_and_new_enrollment_cannot_inherit_pending_alert'),
                'push-revision': ('_record', 'if current != recipient:', 'if False:', 'test_rotation_during_http_fences_old_result_and_retries_successor'),
                'push-capture': ('_initialize_fanout', 'eligible_from<=%s', 'created_at<=%s', 'test_pending_alert_follows_rotation_before_or_after_fanout'),
                'push-conflict': ('_replace_subscription', 'if existing and (', 'if False and (', 'test_rotation_chain_survives_restart_and_refuses_merging_devices'),
                'push-incarnation': ('_replace_subscription', 'or existing[2] != predecessor[0]', '', 'test_old_rotation_retry_cannot_reconnect_removed_successor'),
                'push-removal': ('_remove_subscription', 'actual = recipient.subscription_id if recipient else None', 'actual = None', 'test_removal_follows_current_successor_but_never_an_independent_reenrollment'),
                'push-chain-interval': ('resolve', 'if eligibility is not None and recipient.eligible_from != eligibility:', 'if False:', 'test_removal_follows_current_successor_but_never_an_independent_reenrollment'),
            }[name]
            selection = 'tests/sentinel/test_notification_recovery.py::' + selection
        source = textwrap.dedent(inspect.getsource(getattr(owner, attribute)))
        assert old in source, 'mutation seam disappeared'
        namespace = dict(module.__dict__)
        exec(compile(source.replace(old, new), module.__file__, 'exec'), namespace)
        compiled = namespace[attribute]
        mutant = types.FunctionType(compiled.__code__, module.__dict__, attribute, compiled.__defaults__)
        mutant.__kwdefaults__ = compiled.__kwdefaults__
        return owner, attribute, mutant, selection
    if name in {'migration-stop', 'migration-replay', 'migration-feed-core', 'migration-feed-bootstrap'}:
        import importlib
        import os
        import textwrap
        import types
        root = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[1])
        sys.path.insert(0, str(root / 'scripts'))
        bootstrap = name == 'migration-feed-bootstrap'
        module = importlib.import_module('sentinel_autonomous_deploy_bootstrap' if bootstrap
                                         else 'sentinel_autonomous_deploy')
        owner = module.BootstrapDeploy if bootstrap else module.AutonomousDeploy
        attribute = '_quiesce_database' if name == 'migration-stop' else 'quiesce_backup_and_migrate'
        old, new = {
            'migration-stop': ('self._direct_stop_automation()', 'pass'),
            'migration-replay': ('scripts/sentinel-restore-drill.sh', 'scripts/sentinel-backup-status.sh'),
            'migration-feed-core': ('store.migrate_schema(c);', ''),
            'migration-feed-bootstrap': ('store.migrate_schema(c);', ''),
        }[name]
        source = textwrap.dedent(inspect.getsource(getattr(owner, attribute)))
        assert source.count(old) == 1, 'mutation seam disappeared'
        namespace = dict(module.__dict__)
        exec(compile(source.replace(old, new), module.__file__, 'exec'), namespace)
        compiled = namespace[attribute]
        mutant = types.FunctionType(compiled.__code__, module.__dict__, attribute, compiled.__defaults__)
        mutant.__kwdefaults__ = compiled.__kwdefaults__
        selection = ('test_bootstrap_autonomous_deploy_cannot_skip_feed_migration' if bootstrap else
                     'test_core_autonomous_deploy_migrates_feed_only_after_quiesce_and_replay')
        return owner, attribute, mutant, 'tests/sentinel/test_issue_165_feed_schema.py::' + selection

    from sentinel.automation import outbox
    from sentinel.execution import fill_integrity
    from sentinel.feed import action_history

    recovery = {
        'callback-marker': ('sentinel.automation_supervisor', '_callback_deadline_expired',
            'or invocation is not None and watch.invocation != invocation', 'or False',
            'test_supervisor_dependency_bounds.py::test_same_phase_invocations_get_separate_deadlines_but_one_cannot_renew'),
        'inactive-anchor': ('sentinel.core.rolling_continuity', 'prepare',
            'if missing := protected.difference(series):', 'if False:',
            'test_returning_identity.py::test_missing_economic_dependency_anchor_is_not_inactive_reentry'),
        'dated-return': ('sentinel.core.rolling_inputs', 'SnapshotReferences.current_metadata',
            'sorted(dated or rows,', 'sorted(rows,',
            'test_returning_identity.py::test_return_restarts_features_without_admission_and_survives_restart'),
        'alert-duration': ('sentinel.automation.outbox', 'mark_failed',
            'if not retryable:', 'if not retryable or attempt >= maximum:',
            'test_notification_recovery.py::test_long_outage_and_repeated_worker_death_preserve_delivery_identity'),
        'mixed-recipient': ('sentinel.web_push', 'WebPushAlertAdapter.deliver',
            'any(item[1] for item in failures)', 'all(item[1] for item in failures)',
            'test_notification_recovery.py::test_permanent_peer_cannot_discard_temporary_recipient'),
        'waiting-claim': ('sentinel.feed.rolling_jobs', 'claim',
            'raise JobWaiting(', 'raise JobRefused(',
            'test_rolling_snapshot_jobs.py::test_an_active_owner_excludes_a_second_worker'),
        'retention-diagnostic': ('sentinel.feed.retention', 'maintain',
            'conn.execute("SET LOCAL lock_timeout=\'250ms\'")\n        conn.execute("SET LOCAL statement_timeout=\'1s\'")',
            'pass', 'test_dependency_recovery.py::test_post_commit_retention_diagnostic_has_its_own_lock_budget'),
        'reconstruction-time': ('sentinel.rolling_reconstruction_evidence', 'validate_timing',
            'if not valid:', 'if False:',
            'test_rolling_recovery.py::test_reconstruction_clock_cannot_claim_timely_authority'),
        'reconstruction-date': ('sentinel.rolling_reconstruction_evidence', 'require_dated',
            'if row is None or not shadow_runtime.publication_not_before(pub.window_end) <= row[0] < opened:',
            'if False:', 'test_rolling_recovery.py::test_late_publication_cannot_be_backdated'),
        'reconstruction-authority': ('sentinel.rolling_runtime', '_result',
            'if isinstance(value, authority.ReconstructionReceipt):', 'if False:',
            'test_rolling_recovery.py::test_expired_genesis_candidate_recovers_without_reset_or_replay'),
        'retention-schema': ('sentinel.feed.history_retention_catalog', 'require_recovery_pin',
            'if row is None or " ".join(row[0].split()) != " ".join(expected.split()):', 'if False:',
            'test_rolling_recovery.py::test_stale_retention_rule_is_refused_without_runtime_migration'),
        'shadow-latch': ('sentinel.shadow_supervisor', 'run',
            'if latched:', 'if False:',
            'test_supervisor_dependency_bounds.py::test_persistent_shadow_latch_survives_restart_without_worker'),
        'reconstruction-health': ('sentinel.shadow_supervisor', '_health_snapshot',
            'if health.get("service_health") == "RECONSTRUCTION_PENDING":', 'if False:',
            'test_supervisor_dependency_bounds.py::test_reconstructed_shadow_is_not_green_health'),
        'health-recurrence': ('sentinel.alert_service', '_observe_health',
            'if health.healthy:', 'if False:',
            'test_notification_recovery.py::test_health_recurrence_survives_restart_without_duplicate_active_alert'),
        'dispatcher-deadline': ('sentinel.alert_supervisor', 'run_worker',
            'if remaining <= 0:', 'if False:',
            'test_alert_supervisor.py::test_silent_socket_worker_is_killed_and_reaped'),
        'deployment-global-fence': ('sentinel.deployment_fence', 'require',
            'if control is None or control[0] is not True or lease is None or lease != (None, None, None):',
            'if False:', 'test_deployment_fence.py::test_unfenced_or_partial_database_cannot_enter_migration[released-kill]'),
    }
    if name in recovery:
        import importlib
        import textwrap
        from types import FunctionType
        module_name, path, old, new, selection = recovery[name]
        module = importlib.import_module(module_name)
        target = module
        parts = path.split('.')
        for part in parts[:-1]:
            target = getattr(target, part)
        attribute = parts[-1]
        source = textwrap.dedent(inspect.getsource(getattr(target, attribute)))
        assert source.count(old) == 1, 'mutation seam disappeared'
        namespace = dict(module.__dict__)
        exec(compile(source.replace(old, new), module.__file__, 'exec'), namespace)
        compiled = namespace[attribute]
        # Tests replace clock/provider seams on the live module. A copied
        # globals dictionary would silently bypass those fixture seams and
        # could turn an unrelated refusal into a false passing mutant.
        mutant = FunctionType(compiled.__code__, module.__dict__, compiled.__name__,
                              compiled.__defaults__, compiled.__closure__)
        mutant.__kwdefaults__ = compiled.__kwdefaults__
        return target, attribute, mutant, 'tests/sentinel/' + selection
    if name == 'database-transient':
        from sentinel import dependency_availability
        return dependency_availability, 'database_unavailable', lambda _: False, (
            'tests/sentinel/test_dependency_recovery.py::'
            'test_real_query_timeout_recovers_and_permission_refusal_stays_terminal')
    if name == 'panel-thread':
        from sentinel.panel import push_enrollment
        async def on_loop(function):
            return function()
        return push_enrollment, 'run_in_threadpool', on_loop, (
            'tests/sentinel/test_notification_recovery.py::'
            'test_waiting_subscription_database_does_not_block_event_loop')
    if name == 'integrity-alert':
        from sentinel import alert_service
        return alert_service, '_active_incident', lambda _: False, (
            'tests/sentinel/test_notification_recovery.py::'
            'test_missing_authority_flags_cannot_silence_integrity_alarm')
    if name in {'deploy-timeout', 'deploy-late', 'deploy-fence-order'}:
        import textwrap
        from tests.scripts.test_sentinel_reviewed_deploy_gate import deploy
        target, attribute = deploy.AutonomousDeploy, '_wait_operational'
        old, new, selection = (
            ('self._automation_status(timeout=remaining)', 'self._automation_status()',
             'test_health_wait_bounds_actual_status_subprocess[0.5]')
            if name == 'deploy-timeout' else
            ('if time.monotonic() >= deadline:', 'if False:',
             'test_health_returned_after_deadline_is_refused'))
        if name == 'deploy-fence-order':
            attribute = '_quiesce_database'
            old = 'if proof.get("status") not in {"DURABLY_FENCED", "EMPTY_BEHAVIORAL_SCHEMA"}:'
            new = 'if False:'
            selection = 'test_unfenced_migration_stops_before_backup_and_schema_commands'
        source = textwrap.dedent(inspect.getsource(getattr(target, attribute)))
        assert source.count(old) == 1, 'mutation seam disappeared'
        namespace = dict(deploy.__dict__)
        exec(compile(source.replace(old, new), deploy.__file__, 'exec'), namespace)
        return target, attribute, namespace[attribute], 'tests/scripts/test_deployment_recovery.py::' + selection

    if name == 'fills':
        return (fill_integrity, 'validate', lambda *args: None,
                'tests/sentinel/test_native_fill_acceptance.py::'
                'test_native_fill_authority_requires_order_economic_coherence')
    if name == 'coverage':
        return (action_history, 'verify_coverage_chain', lambda *args, **kwargs: None,
                'tests/sentinel/test_retained_coverage_closure.py::'
                'test_missing_required_coverage_refuses_before_reconciliation[1]')
    if name == 'durable-fills':
        return (fill_integrity, 'validate_durable', lambda *args: None,
                'tests/sentinel/test_native_fill_acceptance.py::'
                'test_complete_native_history_cannot_replace_durable_execution_ids')
    if name == 'push-attempt':
        from sentinel.web_push import WebPushAlertAdapter
        original = WebPushAlertAdapter._record
        def unfenced(self, **kwargs):
            return original(self, **dict(kwargs, claim=None))
        return (WebPushAlertAdapter, '_record', unfenced,
                'tests/sentinel/test_web_push_attempt_fencing.py::'
                'test_push_response_after_takeover_cannot_complete_successor')
    if name == 'snapshot-replay':
        import textwrap
        from sentinel.execution.alpaca import FinancialGradeAlpacaExecutionBroker as module
        attribute = '_bounded_activity_events'
        source = textwrap.dedent(inspect.getsource(getattr(module, attribute)))
        old = 'if replay != snapshot:'
        assert source.count(old) == 1, 'mutation seam disappeared'
        from sentinel.execution import alpaca
        namespace = dict(alpaca.__dict__)
        exec(compile(source.replace(old, 'if False:'), alpaca.__file__, 'exec'), namespace)
        return (module, attribute, namespace[attribute],
                'tests/sentinel/test_alpaca_postclose_candidates.py::'
                'test_candidate_snapshot_replay_refuses_changed_history')
    if name in ('terminal-split', 'restore-origin'):
        if name == 'terminal-split':
            from sentinel.controller import terminal_returns as module
            attribute, old, new = 'values', 'consideration * split * signal', 'consideration * signal'
            selection = 'tests/sentinel/test_terminal_split_return.py'
        else:
            from sentinel import restore_validation as module
            attribute, old, new = '_rolling_closure', 'if rolling_checkpoint.lineage_names(conn):', 'if False:'
            selection = ('tests/sentinel/test_rolling_restore_integrity.py::'
                         'test_restore_refuses_corrupt_current_rolling_dependencies[missing-origin]')
        source = inspect.getsource(getattr(module, attribute))
        assert source.count(old) == 1, 'mutation seam disappeared'
        namespace = dict(module.__dict__)
        exec(compile(source.replace(old, new), module.__file__, 'exec'), namespace)
        return module, attribute, namespace[attribute], selection
    source = inspect.getsource(outbox.mark_failed)
    for old, new in (
        (' AND delivery_holder=%s AND attempt_count=%s', ' AND delivery_holder=%s'),
        ('(alert_id, holder_id, attempt)', '(alert_id, holder_id)')):
        assert source.count(old) == 1, 'mutation seam disappeared'
        source = source.replace(old, new)
    namespace = dict(outbox.__dict__)
    exec(compile(source, outbox.__file__, 'exec'), namespace)
    mutant = namespace['mark_failed']
    return (outbox, 'mark_failed', mutant,
            'tests/sentinel/test_alert_attempt_fencing.py::'
            'test_old_attempt_cannot_finish_successor_even_with_same_holder[failure]')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mutation', choices=('fills', 'coverage', 'attempt',
                                            'durable-fills', 'terminal-split', 'restore-origin', 'push-attempt',
                                            'snapshot-replay', 'callback-marker', 'inactive-anchor',
                                            'dated-return', 'alert-duration', 'mixed-recipient',
                                            'waiting-claim', 'database-transient', 'panel-thread',
                                            'integrity-alert', 'deploy-timeout', 'deploy-late',
                                            'retention-diagnostic', 'reconstruction-time', 'reconstruction-date',
                                            'reconstruction-authority', 'retention-schema', 'shadow-latch',
                                            'reconstruction-health', 'health-recurrence', 'dispatcher-deadline',
                                            'deployment-global-fence', 'deploy-fence-order',
                                            'migration-stop', 'migration-replay',
                                            'migration-feed-core', 'migration-feed-bootstrap',
                                            'stream-deadline', 'push-successor', 'push-eligibility',
                                            'push-revision', 'push-capture', 'push-serialization',
                                            'stream-group', 'push-conflict', 'push-incarnation',
                                            'push-removal', 'push-chain-interval'))
    name = parser.parse_args().mutation
    module, attribute, mutant, selection = case(name)
    args = [selection, '-q', '--tb=short', '--show-capture=no', '-p', 'no:cacheprovider']
    if pytest.main(args) != pytest.ExitCode.OK:
        raise SystemExit('Unmodified acceptance case must pass first')
    with patch.object(module, attribute, mutant):
        result = pytest.main(args)
    if result != pytest.ExitCode.TESTS_FAILED:
        raise SystemExit(f'Mutation was not detected: {name} ({result})')
    print(f'MUTATION_RESULT {name}: KILLED')


if __name__ == '__main__':
    main()
