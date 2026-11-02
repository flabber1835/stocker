"""Pure boundary tests. No canonical/financial runtime or container is loaded."""
from copy import deepcopy
import json
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import system_campaign_close_scope as scope


SID = '533554648046407798'
PRED = '1' * 64
EVIDENCE = [dict(reference=f'research:test/{i}', description='fixture', sha256=str(i) * 64)
            for i in range(3)]


def body():
    return dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=PRED,
                source_evidence=[], suppress=[dict(session='2023-11-06', security_id=SID,
                term_sha256='2' * 64)], add=[])


def document():
    return dict(schema=scope.SCHEMA, predecessor_checkpoint_sha256=PRED, scope=scope.SCOPE,
                require_unowned_and_unordered=True, require_no_entry_intents=True, morning_settlement_claimed=False,
                canonical_repair=body(), source_evidence=deepcopy(EVIDENCE))


def load(tmp_path, value=None, **changes):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(document() if value is None else value))
    return scope.parse(path, **dict(dict(resume_session='2023-10-31',
                        predecessor_checkpoint_sha256=PRED, expected_repair=body(),
                        expected_evidence=EVIDENCE), **changes))


def state(label, *, episodes=None, pending=None):
    return SimpleNamespace(state_hash=label, wealth_core={'episodes': episodes or {}},
                           pending=[] if pending is None else pending,
                           last_evidence={'wealth_core': {'intents': []}})


def make_guard(tmp_path, before=None, after=None):
    obj = load(tmp_path)
    guard = scope.TransitionGuard(SimpleNamespace(objects=[obj]))
    before = state('before') if before is None else before
    after = state('after') if after is None else after
    run = SimpleNamespace(state=before, input_sha256='3' * 64)
    result = SimpleNamespace(state=after)
    guard.original_advance = lambda actual, published: result
    return guard, run, result


def record(day='2023-11-06', label='after', wealth=None, pending=None):
    wealth = {'episodes': {}} if wealth is None else wealth
    pending = [] if pending is None else pending
    return dict(session=day, state_sha256=label, input_sha256='3' * 64,
                evidence=dict(research_entry_audit=dict(closing_accounting=dict(
                    wealth_core=wealth, pending=pending)), wealth_core=dict(intents=pending)))


def test_input_own_binding_and_distinct_scope(tmp_path):
    obj = load(tmp_path)
    assert obj.earliest_affected_session == '2023-11-06'
    assert len(obj.sha256) == 64
    assert obj.model_dump(by_alias=True)['schema'] != 'terminal-repair/1'
    with pytest.raises(ValueError, match='EXACT_OWN_PREDECESSOR'):
        load(tmp_path, predecessor_checkpoint_sha256='0' * 64)
    with pytest.raises(ValueError, match='UNCONSUMED'):
        load(tmp_path, resume_session='2023-11-06')
    changed = body(); changed['suppress'][0]['term_sha256'] = '4' * 64
    with pytest.raises(ValueError, match='INDEPENDENTLY_ASSEMBLED'):
        load(tmp_path, expected_repair=changed)


@pytest.mark.parametrize('field,value', [('require_unowned_and_unordered', 1),
    ('require_unowned_and_unordered', False), ('morning_settlement_claimed', True),
    ('morning_settlement_claimed', 0), ('extra', 'ignored')])
def test_scope_cannot_be_relaxed(tmp_path, field, value):
    doc = document(); doc[field] = value
    with pytest.raises(ValueError):
        load(tmp_path, doc)


@pytest.mark.parametrize('value', [False, 1, 'true'])
def test_entry_intent_boolean_is_exact(tmp_path, value):
    doc = document();doc['require_no_entry_intents'] = value
    with pytest.raises(ValueError): load(tmp_path, doc)


@pytest.mark.parametrize('when', ['before', 'after'])
def test_signalled_but_not_pending_entry_intent_refuses(tmp_path, when):
    guard, run, result = make_guard(tmp_path)
    changed = run.state if when == 'before' else result.state
    changed.last_evidence['wealth_core']['intents'] = [{'security_id': SID}]
    with pytest.raises(ValueError, match='NO_SIGNALLED_ENTRY_INTENT'):
        guard.advance(run, SimpleNamespace(session='2023-11-06'))
    assert guard.pending is None and guard.failure['financial_row_committed'] is False


def test_actual_intent_guard_removal_falsifier():
    with pytest.raises(ValueError): scope.require_intents([{'security_id': SID}], [SID])
    fn, = [n for n in ast.parse(Path(scope.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'require_intents']
    fn.body = [ast.Pass()]
    namespace = dict(vars(scope))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-intent-guard-removed>', 'exec'), namespace)
    namespace['require_intents']([{'security_id': SID}], [SID])


@pytest.mark.parametrize('field', ['unresolved_terminals', 'terminal_pending_terms',
                                  'terminal_pending_sessions', 'terminal_carry_audit'])
def test_unheld_terminal_claim_cannot_bypass_scope(field):
    core = {'episodes': {}, field: {SID: 'claim'}}
    with pytest.raises(ValueError, match='NO_UNRESOLVED_OR_PENDING_TERMINAL_CLAIM'):
        scope.require_absent(core, [], [SID])


def test_nested_duplicate_json_is_refused(tmp_path):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(document()).replace('"add": []', '"add": [], "add": []'))
    with pytest.raises(ValueError, match='DUPLICATE_JSON_KEY'):
        scope.parse(path, resume_session='2023-10-31', predecessor_checkpoint_sha256=PRED,
                    expected_repair=body(), expected_evidence=EVIDENCE)


@pytest.mark.parametrize('when,kind', [('before', 'OWNED'), ('before', 'ORDERED'),
                                     ('after', 'OWNED'), ('after', 'ORDERED')])
def test_both_sides_refuse_position_or_order(tmp_path, when, kind):
    changed = state(when, episodes={'x': {'security_id': SID}} if kind == 'OWNED' else None,
                    pending=[{'security_id': SID}] if kind == 'ORDERED' else None)
    guard, run, _ = make_guard(tmp_path, **{when: changed})
    with pytest.raises(ValueError, match='MUST_NOT_BE_' + kind):
        guard.advance(run, SimpleNamespace(session='2023-11-06'))
    assert guard.pending is None and guard.failure['financial_row_committed'] is False


def test_watch_and_review_bind_actual_rows_and_reject_mutations(tmp_path):
    guard, run, result = make_guard(tmp_path)
    assert guard.advance(run, SimpleNamespace(session='2023-11-06')) is result
    writes = []
    guard.original_append = lambda owner, name, row: writes.append((name, deepcopy(row)))
    current = record(); previous = record('2023-11-03', 'before')
    guard.append(object(), 'daily', current)
    assert [n for n, _ in writes] == ['watch', 'daily'] and guard.pending is None
    proof = writes[0][1]
    reviewed = scope.review_guards([previous, current], [proof],
                                  guarded_input_sha256=guard.codec.objects[0].sha256)
    assert reviewed['rows'] == 1
    for changed in ({**proof, 'prior_state_sha256': 'wrong'},
                    {**proof, 'guarded_input_sha256': '0' * 64},
                    {**proof, 'financial_row_sha256': '0' * 64}):
        with pytest.raises(ValueError, match='EVERY_ACTUAL_POSITION_STATE_AND_ROW_BOUND'):
            scope.review_guards([previous, current], [changed],
                                guarded_input_sha256=guard.codec.objects[0].sha256)
    for rows in ([], [proof, proof]):
        with pytest.raises(ValueError, match='EXACT_GUARD_AND_FINANCIAL_AXIS'):
            scope.review_guards([previous, current], rows,
                                guarded_input_sha256=guard.codec.objects[0].sha256)
    # Independent review checks the actual snapshots, rather than trusting the
    # runtime claim that the scoped security was absent.
    owned = deepcopy(current)
    owned['evidence']['research_entry_audit']['closing_accounting']['wealth_core']['episodes']['x'] = {'security_id': SID}
    with pytest.raises(ValueError, match='MUST_NOT_BE_OWNED'):
        scope.review_guards([previous, owned], [proof],
                            guarded_input_sha256=guard.codec.objects[0].sha256)


def test_missing_or_mismatched_pending_proof_refuses(tmp_path):
    guard, run, _ = make_guard(tmp_path)
    guard.original_append = lambda *args: None
    with pytest.raises(ValueError, match='EXACT_ACTUAL_FINANCIAL_ROW'):
        guard.append(object(), 'daily', record())
    guard.advance(run, SimpleNamespace(session='2023-11-06'))
    with pytest.raises(ValueError, match='PREVIOUS_TRANSITION_NOT_COMMITTED'):
        guard.advance(run, SimpleNamespace(session='2023-11-07'))
    with pytest.raises(ValueError, match='EXACT_ACTUAL_FINANCIAL_ROW'):
        guard.append(object(), 'daily', {**record(), 'input_sha256': 'wrong'})


def test_new_name_activates_on_its_own_native_date():
    assert scope.active('2023-11-03') == []
    assert scope.active('2023-11-06') == [SID]
    assert scope.active('2023-11-08') == sorted(scope.NATIVES)


def test_completion_storage_hook_requests_actual_canonical_predecessor(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    original = {'terminal': ['retained'], 'spinoff': []}
    guard.original_relevant = lambda *args: original
    assert guard.relevant(None, SimpleNamespace(day='2023-11-06')) is original
    result = guard.relevant(None, SimpleNamespace(day='2023-11-07'))
    assert result['terminal'] == original['terminal']
    assert 'research_close_scope' not in original
    assert result['research_close_scope']['security_ids'] == [SID]
    assert result['research_close_scope']['guarded_input_sha256'] == guard.codec.objects[0].sha256


def test_carried_pending_orders_are_not_equated_to_new_intents(tmp_path):
    queue = [{'security_id': 'OTHER', 'sessions_waiting': 2, 'intended_dollars': 100.}]
    guard, run, _ = make_guard(tmp_path, before=state('before', pending=queue),
                               after=state('after', pending=queue))
    guard.advance(run, SimpleNamespace(session='2023-11-06'))
    writes = []
    guard.original_append = lambda owner, name, row: writes.append((name, deepcopy(row)))
    previous = record('2023-11-03', 'before', pending=queue)
    current = record(pending=queue)
    current['evidence']['wealth_core']['intents'] = []
    guard.append(object(), 'daily', current)
    assert scope.review_guards([previous, current], [writes[0][1]],
                guarded_input_sha256=guard.codec.objects[0].sha256)['rows'] == 1
    current['evidence']['wealth_core']['intents'] = [{'security_id': SID}]
    with pytest.raises(ValueError, match='MUST_NOT_BE_ORDERED'):
        scope.review_guards([previous, current], [writes[0][1]],
                            guarded_input_sha256=guard.codec.objects[0].sha256)


def test_guard_removal_falsifier(tmp_path, monkeypatch):
    """Removing the real projection guard must break the owned-case test."""
    def expect_owned_refusal():
        guard, run, _ = make_guard(tmp_path, after=state('after', episodes={'x': {'security_id': SID}}))
        try:
            guard.advance(run, SimpleNamespace(session='2023-11-06'))
        except ValueError as exc:
            assert 'MUST_NOT_BE_OWNED' in str(exc)
        else:
            raise AssertionError('owned-case regression test would fail')
    expect_owned_refusal()
    monkeypatch.setattr(scope, 'require_absent', lambda *args: None)
    with pytest.raises(AssertionError, match='regression test would fail'):
        expect_owned_refusal()


def test_no_canonical_import_at_module_load():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(scope.__file__).read_bytes())
    imports = [node.module for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert all(not name.startswith(('sentinel.', 'stock_strategy_shared.', 'research.pooled_'))
               for name in imports)
