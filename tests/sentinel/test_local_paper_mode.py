"""Owner-authorized PAPER iteration does not open a live or foreign account."""
from datetime import date
from types import SimpleNamespace
import ast
import inspect

import pytest

from sentinel import backup_guard, backup_runtime_authority, binding, local_paper
from sentinel.execution import alpaca


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PATESTACCOUNT")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setattr(binding, "require", lambda conn: SimpleNamespace(
        broker="alpaca", broker_account_id="PATESTACCOUNT"))


def test_mode_is_opt_in(monkeypatch):
    monkeypatch.delenv(local_paper.MODE_ENV, raising=False)
    assert not local_paper.enabled()


@pytest.mark.parametrize("endpoint", ["https://api.alpaca.markets", "http://paper-api.alpaca.markets", "https://paper-api.alpaca.markets.evil.test"])
def test_local_mode_never_allows_live_or_proxy(owner, monkeypatch, endpoint):
    monkeypatch.setenv("ALPACA_BASE_URL", endpoint)
    with pytest.raises(RuntimeError):
        local_paper.enabled()


def test_foreign_binding_refuses(owner, monkeypatch):
    monkeypatch.setattr(binding, "require", lambda conn: SimpleNamespace(
        broker="alpaca", broker_account_id="PAFOREIGN"))
    with pytest.raises(RuntimeError, match="durable binding"):
        local_paper.require_bound_account(object())
    with pytest.raises(RuntimeError, match="durable binding"):
        backup_runtime_authority.require(object(), operation="paper order")


class NoBackupReads:
    def cursor(self):
        pytest.fail("local PAPER mode attempted a backup or restart probe")


def test_no_backup_reads_or_restored_horizon_required(owner):
    conn = NoBackupReads()
    assert backup_runtime_authority.require(conn, operation="paper order") == {"enabled": False}
    result = backup_guard.require_writes_permitted(conn, operation="paper order")
    assert result.state == "DISABLED_BY_OPERATOR"
    assert result.writes_permitted
    assert backup_guard.require_bulk_writes_permitted(conn, operation="feed").bulk_writes_permitted


def test_intraday_restart_is_not_a_local_paper_increase_fence(owner):
    conn = NoBackupReads()
    assert alpaca.postmaster_day_order_fence_reason(conn, date(2026, 10, 21)) == ""
    assert alpaca.upgrade_restore_reason(conn) == ""
    assert alpaca.execution_increase_fence_reason(
        conn=conn, deployment=SimpleNamespace(broker="alpaca"), today=date(2026, 10, 21)) == ""


def _runtime(monkeypatch):
    commit = "a" * 40
    digest = "sha256:" + "b" * 64
    monkeypatch.setenv("SENTINEL_GIT_COMMIT", commit)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", commit)
    monkeypatch.setenv("SENTINEL_RUNTIME_IMAGE_DIGEST", digest)
    return {"deployment_artifacts": {"schema": "sentinel.runtime-artifacts/1",
        "git_commit": commit, "runtime_image_digest": digest, "test_image_digest": digest}}


def test_local_runtime_records_actual_commit_and_image(owner, monkeypatch):
    local_paper.require_runtime(object(), _runtime(monkeypatch))


def _bad_baked_revision(monkeypatch):
    runtime = _runtime(monkeypatch)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "c" * 40)
    with pytest.raises(RuntimeError, match="actual local commit"):
        local_paper.require_runtime(object(), runtime)


def test_mislabelled_local_image_refuses(owner, monkeypatch):
    _bad_baked_revision(monkeypatch)


def test_runtime_identity_guard_falsifier(owner, monkeypatch):
    tree = ast.parse(inspect.getsource(local_paper.validate_runtime_identity))
    tree.body[0].body[-1].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, "removed-local-image-guard", "exec"), vars(local_paper), namespace)
    monkeypatch.setattr(local_paper, "validate_runtime_identity", namespace["validate_runtime_identity"])
    with pytest.raises(pytest.fail.Exception):
        _bad_baked_revision(monkeypatch)


def _continuation_fixture(monkeypatch, *, recovered=True, terminal=True):
    from sentinel.automation import integrity, local_paper_continuation as continuation
    from sentinel.automation.model import CycleState
    monkeypatch.setattr(integrity, 'validate_cycle_lineage', lambda *args: None)
    spec = SimpleNamespace(control_generation=30, deployment_id='local', broker='alpaca',
        broker_account_id='PATESTACCOUNT', takeover_epoch=1, decision_session=date(2026, 10, 20),
        effective_session=date(2026, 10, 21))
    cycle = SimpleNamespace(**vars(spec))
    cycle.control_generation = 28
    cycle.state = CycleState.SUPERSEDED
    cycle.failure_code = 'OLD_GENERATION_RECOVERED'
    cycle.historical_state_only = False
    cycle.plan_id = 'prior-plan'
    cycle.last_clean_reconciliation_id = '44'
    cycle.diagnostic = dict(clean=True, unresolved=[], foreign_orders=[], foreign_positions=[])
    answers = iter([(recovered,), (not terminal,)])
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return next(answers)
    conn = SimpleNamespace(cursor=Cursor)
    config = SimpleNamespace(debug_window_for=lambda spec: object())
    return continuation, dict(conn=conn, spec=spec, cycles=[cycle], config=config)


def test_local_continuation_requires_native_recovery(owner, monkeypatch):
    continuation, args = _continuation_fixture(monkeypatch)
    assert continuation.eligible(**args)


@pytest.mark.parametrize('recovered,terminal', [(False, True), (True, False)])
def test_unproven_or_working_predecessor_refuses(owner, monkeypatch, recovered, terminal):
    continuation, args = _continuation_fixture(monkeypatch, recovered=recovered, terminal=terminal)
    assert not continuation.eligible(**args)


@pytest.mark.parametrize('change', [dict(state='EXECUTING'), dict(failure_code='arbitrary'),
    dict(last_clean_reconciliation_id=None), dict(broker_account_id='PAFOREIGN'),
    dict(control_generation=30), dict(diagnostic={'clean': False})])
def test_continuation_never_reopens_unrecovered_intent(owner, monkeypatch, change):
    continuation, args = _continuation_fixture(monkeypatch)
    for name, value in change.items():
        setattr(args['cycles'][0], name, value)
    assert not continuation.eligible(**args)


def test_continuation_terminal_guard_falsifier(owner, monkeypatch):
    continuation, args = _continuation_fixture(monkeypatch, terminal=False)
    tree = ast.parse(inspect.getsource(continuation.eligible))
    loop = next(node for node in tree.body[0].body if isinstance(node, ast.For))
    loop.body[-2].body[-1].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, 'removed-terminal-command-guard', 'exec'), vars(continuation), namespace)
    assert namespace['eligible'](**args), 'mutant must expose the working predecessor'


@pytest.mark.parametrize('changed', [False, True])
def test_retained_local_process_preserves_book_and_requires_current_bytes(owner, monkeypatch, changed):
    from sentinel import runtime_admission as admission, rolling_daily_checkpoint as daily
    actual = _runtime(monkeypatch)
    actual['identity_hash'] = 'd'*64
    monkeypatch.setattr(admission.identity, 'rehearsal_identity', lambda: actual)
    config = {'validated_source_identity_sha256': 'old-source', 'observation_id': 'primary'}
    old_runtime = {'schema': 'sentinel.shadow-runtime-identity/1', 'reviewed_shadow_config': config}
    strategy = {'strategy': 'unchanged-canonical'}
    checkpoint = SimpleNamespace(observation_id='primary', starting_cash='50000',
        strategy_identity=strategy, runtime_identity=old_runtime)
    monkeypatch.setattr(admission.origin, 'read', lambda conn: checkpoint)
    monkeypatch.setattr(daily, 'read', lambda conn: None)
    monkeypatch.setattr(admission, 'read', lambda *args: pytest.fail('local process attempted release admission read'))
    runtime = dict(old_runtime, git_commit='a'*40, runtime_image_digest='sha256:'+'b'*64,
        environment_identity_sha256=('e' if changed else 'd')*64)
    context = dict(observation_id='primary', starting_cash='50000', strategy=strategy, runtime=runtime)
    if changed:
        with pytest.raises(admission.Refused, match='PROCESS_IDENTITY_CHANGED'):
            admission.bind_context(object(), context)
    else:
        admission.bind_context(object(), context)
        assert context['runtime'] is old_runtime
        assert checkpoint.runtime_identity == old_runtime


@pytest.mark.parametrize('changed', [False, True])
def test_local_execution_config_must_be_actual_protected_policy(owner, monkeypatch, changed):
    from sentinel.authority import canonical_sha256, execution_config_identity
    monkeypatch.setenv('SENTINEL_PAPER_BUY_POLICY', 'PROTECTED_LIMIT_DAY_V1')
    monkeypatch.setenv('SENTINEL_PAPER_BUY_CAP_BPS', '100')
    monkeypatch.delenv('SENTINEL_PAPER_DEBUG_WINDOW', raising=False)
    actual = canonical_sha256(execution_config_identity(paper_base_url='https://paper-api.alpaca.markets'))
    if changed:
        with pytest.raises(RuntimeError, match='differs from actual'):
            local_paper.require_execution_config(object(), '0'*64)
    else:
        local_paper.require_execution_config(object(), actual)


def test_local_execution_configuration_guard_falsifier(owner, monkeypatch):
    tree = ast.parse(inspect.getsource(local_paper.validate_execution_policy))
    tree.body[0].body[-1].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, 'removed-local-policy-guard', 'exec'), vars(local_paper), namespace)
    monkeypatch.setattr(local_paper, 'validate_execution_policy', namespace['validate_execution_policy'])
    with pytest.raises(pytest.fail.Exception):
        test_local_execution_config_must_be_actual_protected_policy(owner, monkeypatch, True)


def test_retained_process_identity_guard_falsifier(owner, monkeypatch):
    from sentinel import runtime_admission as admission
    tree = ast.parse(inspect.getsource(admission.bind_context))
    guard = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
        and any(isinstance(item, ast.Constant) and item.value == 'LOCAL_PAPER_RETAINED_PROCESS_IDENTITY_CHANGED'
                for child in node.body if isinstance(child, ast.Raise) for item in ast.walk(child)))
    guard.test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, 'removed-retained-local-process-guard', 'exec'), vars(admission), namespace)
    monkeypatch.setattr(admission, 'bind_context', namespace['bind_context'])
    with pytest.raises(pytest.fail.Exception):
        test_retained_local_process_preserves_book_and_requires_current_bytes(owner, monkeypatch, True)


def _resizing_fixture(monkeypatch, *, working=False):
    import json
    from sentinel.paper import preparation
    from sentinel.automation import integrity, store
    from sentinel.execution import target_reprojection
    from sentinel.execution.states import CommandState
    monkeypatch.setenv('SENTINEL_PAPER_BUY_POLICY', 'PROTECTED_LIMIT_DAY_V1')
    monkeypatch.setenv('SENTINEL_PAPER_BUY_CAP_BPS', '100')
    monkeypatch.setenv('SENTINEL_PAPER_DEBUG_WINDOW', json.dumps(dict(schema='PAPER_DEBUG_WINDOW_V1',
        effective_session='2026-10-21',not_before='2026-10-21T19:00:00Z',not_after='2026-10-21T19:30:00Z')))
    plan=SimpleNamespace(plan_id='old-plan',effective_session=date(2026,10,21))
    cycle=SimpleNamespace(cycle_id='current-cycle',control_generation=32,config_sha256='c'*64,effective_session=plan.effective_session)
    grant=SimpleNamespace(cycle_id=cycle.cycle_id,operation_scope='PREPARE',control_generation=32,config_sha256=cycle.config_sha256)
    monkeypatch.setattr(target_reprojection,'load_projection',lambda *args,**kwargs: SimpleNamespace(opening_sizing={'policy':{'prior_window':True}}))
    monkeypatch.setattr(store,'load_cycle',lambda *args: cycle)
    monkeypatch.setattr(integrity,'validate_cycle_lineage',lambda *args: None)
    monkeypatch.setattr(binding,'require',lambda conn: SimpleNamespace(broker='alpaca',broker_account_id='PATESTACCOUNT',identity=object()))
    monkeypatch.setattr(preparation.journal,'load_commands',lambda *args,**kwargs: [SimpleNamespace(state=CommandState.UNKNOWN if working else CommandState.FILLED)])
    monkeypatch.setattr(preparation.journal,'in_flight_commands',lambda *args: [])
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def execute(self,*args): pass
        def fetchone(self): return ({'owner_paper_continuation':local_paper.MODE},)
    return preparation,SimpleNamespace(cursor=Cursor),plan,grant


def test_changed_window_rebuilds_only_after_native_terminal_recovery(owner,monkeypatch):
    module,conn,plan,grant=_resizing_fixture(monkeypatch)
    plan.decision_session=date(2026,10,20)
    assert module._local_window_resizing(conn,plan,grant,decision_session=plan.decision_session)
    with pytest.raises(module.PaperActivationRefused,match='native continuation'):
        module._local_window_resizing(conn,plan,None)


def test_changed_window_cannot_resize_unknown_orders(owner,monkeypatch):
    module,conn,plan,grant=_resizing_fixture(monkeypatch,working=True)
    with pytest.raises(module.PaperRetryableRefused,match='terminal commands'):
        module._local_window_resizing(conn,plan,grant)


def test_resizing_terminal_guard_falsifier(owner,monkeypatch):
    from sentinel.paper import preparation
    tree=ast.parse(inspect.getsource(preparation._local_window_resizing))
    tree.body[0].body[-2].test=ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace={}
    exec(compile(tree,'removed-resizing-terminal-guard','exec'),vars(preparation),namespace)
    monkeypatch.setattr(preparation,'_local_window_resizing',namespace['_local_window_resizing'])
    with pytest.raises(pytest.fail.Exception):
        test_changed_window_cannot_resize_unknown_orders(owner,monkeypatch)


def test_ordinary_next_day_does_not_consume_previous_window(owner,monkeypatch):
    from sentinel.paper import preparation
    from sentinel.execution import target_reprojection
    monkeypatch.setattr(target_reprojection,'load_projection',
        lambda *args,**kwargs: pytest.fail('ordinary next day inspected the old debug projection'))
    old=SimpleNamespace(plan_id='old-plan',decision_session=date(2026,10,20))
    assert preparation._local_window_resizing(object(),old,None,
        decision_session=date(2026,10,21)) is False


def test_resizing_decision_day_guard_falsifier(owner,monkeypatch):
    from sentinel.paper import preparation
    tree=ast.parse(inspect.getsource(preparation._local_window_resizing))
    first_guard=next(node for node in tree.body[0].body if isinstance(node,ast.If))
    first_guard.test=ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace={}
    exec(compile(tree,'removed-resizing-decision-day-guard','exec'),vars(preparation),namespace)
    monkeypatch.setattr(preparation,'_local_window_resizing',namespace['_local_window_resizing'])
    with pytest.raises(pytest.fail.Exception):
        test_ordinary_next_day_does_not_consume_previous_window(owner,monkeypatch)
