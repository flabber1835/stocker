"""Pure boundary tests. No canonical/financial runtime or container is loaded."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import system_campaign_completion_scope as scope


SID = '827416728546053456'
PRED = '1' * 64
EVIDENCE = [dict(reference=f'research:test/{i}', description='fixture', sha256=str(i) * 64)
            for i in range(3)]


def body():
    return dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=PRED,
                source_evidence=[], suppress=[dict(session='2022-10-04', security_id=SID,
                term_sha256='2' * 64)], add=[])


def document():
    return dict(schema=scope.SCHEMA, predecessor_checkpoint_sha256=PRED, scope=scope.SCOPE,
                require_unowned_and_unordered=True, morning_settlement_claimed=False,
                canonical_repair=body(), source_evidence=deepcopy(EVIDENCE))


def load(tmp_path, value=None, **changes):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(document() if value is None else value))
    return scope.parse(path, **dict(dict(resume_session='2022-09-30',
                        predecessor_checkpoint_sha256=PRED, expected_repair=body(),
                        expected_evidence=EVIDENCE), **changes))


def state(label, *, episodes=None, pending=None):
    return SimpleNamespace(state_hash=label, wealth_core={'episodes': episodes or {}},
                           pending=[] if pending is None else pending)


def make_guard(tmp_path, before=None, after=None):
    obj = load(tmp_path)
    guard = scope.TransitionGuard(SimpleNamespace(objects=[obj]))
    before = state('before') if before is None else before
    after = state('after') if after is None else after
    run = SimpleNamespace(state=before, input_sha256='3' * 64)
    result = SimpleNamespace(state=after)
    guard.original_advance = lambda actual, published: result
    return guard, run, result


def record(day='2022-10-04', label='after', wealth=None, pending=None):
    wealth = {'episodes': {}} if wealth is None else wealth
    pending = [] if pending is None else pending
    return dict(session=day, state_sha256=label, input_sha256='3' * 64,
                evidence=dict(research_entry_audit=dict(closing_accounting=dict(
                    wealth_core=wealth, pending=pending)), wealth_core=dict(intents=pending)))


def test_input_own_binding_and_distinct_scope(tmp_path):
    obj = load(tmp_path)
    assert obj.earliest_affected_session == '2022-10-04'
    assert len(obj.sha256) == 64
    assert obj.model_dump(by_alias=True)['schema'] != 'terminal-repair/1'
    with pytest.raises(ValueError, match='EXACT_OWN_PREDECESSOR'):
        load(tmp_path, predecessor_checkpoint_sha256='0' * 64)
    with pytest.raises(ValueError, match='UNCONSUMED'):
        load(tmp_path, resume_session='2022-10-04')
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


def test_nested_duplicate_json_is_refused(tmp_path):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(document()).replace('"add": []', '"add": [], "add": []'))
    with pytest.raises(ValueError, match='DUPLICATE_JSON_KEY'):
        scope.parse(path, resume_session='2022-09-30', predecessor_checkpoint_sha256=PRED,
                    expected_repair=body(), expected_evidence=EVIDENCE)


@pytest.mark.parametrize('when,kind', [('before', 'OWNED'), ('before', 'ORDERED'),
                                     ('after', 'OWNED'), ('after', 'ORDERED')])
def test_both_sides_refuse_position_or_order(tmp_path, when, kind):
    changed = state(when, episodes={'x': {'security_id': SID}} if kind == 'OWNED' else None,
                    pending=[{'security_id': SID}] if kind == 'ORDERED' else None)
    guard, run, _ = make_guard(tmp_path, **{when: changed})
    with pytest.raises(ValueError, match='MUST_NOT_BE_' + kind):
        guard.advance(run, SimpleNamespace(session='2022-10-04'))
    assert guard.pending is None and guard.failure['financial_row_committed'] is False


def test_watch_and_review_bind_actual_rows_and_reject_mutations(tmp_path):
    guard, run, result = make_guard(tmp_path)
    assert guard.advance(run, SimpleNamespace(session='2022-10-04')) is result
    writes = []
    guard.original_append = lambda owner, name, row: writes.append((name, deepcopy(row)))
    current = record(); previous = record('2022-10-03', 'before')
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
    guard.advance(run, SimpleNamespace(session='2022-10-04'))
    with pytest.raises(ValueError, match='PREVIOUS_TRANSITION_NOT_COMMITTED'):
        guard.advance(run, SimpleNamespace(session='2022-10-05'))
    with pytest.raises(ValueError, match='EXACT_ACTUAL_FINANCIAL_ROW'):
        guard.append(object(), 'daily', {**record(), 'input_sha256': 'wrong'})


def test_new_name_activates_on_its_own_native_date():
    assert scope.active('2022-10-03') == []
    assert scope.active('2022-10-04') == [SID]
    assert scope.active('2022-10-10') == sorted(scope.NATIVES)


def test_completion_storage_hook_requests_actual_canonical_predecessor(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    original = {'terminal': ['retained'], 'spinoff': []}
    guard.original_relevant = lambda *args: original
    assert guard.relevant(None, SimpleNamespace(day='2022-10-04')) is original
    result = guard.relevant(None, SimpleNamespace(day='2022-10-05'))
    assert result['terminal'] == original['terminal']
    assert 'research_completion_scope' not in original
    assert result['research_completion_scope']['security_ids'] == [SID]
    assert result['research_completion_scope']['guarded_input_sha256'] == guard.codec.objects[0].sha256


def test_carried_pending_orders_are_not_equated_to_new_intents(tmp_path):
    queue = [{'security_id': 'OTHER', 'sessions_waiting': 2, 'intended_dollars': 100.}]
    guard, run, _ = make_guard(tmp_path, before=state('before', pending=queue),
                               after=state('after', pending=queue))
    guard.advance(run, SimpleNamespace(session='2022-10-04'))
    writes = []
    guard.original_append = lambda owner, name, row: writes.append((name, deepcopy(row)))
    previous = record('2022-10-03', 'before', pending=queue)
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
            guard.advance(run, SimpleNamespace(session='2022-10-04'))
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


def test_public_batch_retains_exact_cash_loader_and_scope():
    from pathlib import Path
    from system_campaign_completion_facts import contract, CATALOG, HERE
    from system_campaign_ordinary_registry import registrations
    c = contract()
    catalog = json.loads((HERE / CATALOG).read_bytes())
    assert len(catalog['terms']) == 17
    assert catalog['commitment_group'] in registrations(HERE)
    assert {e['ticker']: e['added']['cash_per_share'] for e in c['scoped_events']} == {'GBT': 68.5, 'NLSN': 28.}
    assert all(e['preopen_completion_claimed'] is False for e in c['scoped_events'])
    assert c['suppression_only']['preserved_complete']['cash_per_share'] == 39.
    assert c['suppression_only']['native']['session'] == '2023-02-28'
    assert c['suppression_only']['preserved_complete']['session'] == '2023-03-01'


def test_common_semantics_never_mask_duplicates_or_redefined_compilers():
    from system_campaign_completion_basis import merge_semantics
    prior = dict(suppress=[], add=[], declared_fact_compilers={'old': '1' * 64})
    body = dict(suppress=[{'session': '2023-02-28', 'security_id': 'COWN'}], add=[])
    value = merge_semantics(prior, body, {'new': '2' * 64})
    assert value['suppress'] == body['suppress'] and prior['suppress'] == []
    with pytest.raises(ValueError, match='NO_DUPLICATE_OR_CONFLICTING_NEW_EVENT'):
        merge_semantics(value, body, {})
    with pytest.raises(ValueError, match='NO_REDEFINED_COMPILER'):
        merge_semantics(prior, body, {'old': '2' * 64})


def test_semantic_visitor_changes_only_explicit_schema_classification():
    import ast
    from pathlib import Path
    from system_campaign_completion_basis import inherited_visitor, inherited
    original = ast.parse(Path(inherited.old.__file__).read_bytes())
    fn, = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == 'basis']
    # Constructing this semantic visitor executes no canonical/financial calls.
    adapted = inherited_visitor()
    assert adapted.__name__ == fn.name
    assert adapted.__globals__['ADDITIONAL_SCHEMAS'] == {scope.SCHEMA, 'research.zogenix-leadership-uncertainty-input/1'}
    assert adapted.__globals__['ordinary_basis'] is inherited.old.ordinary_basis
