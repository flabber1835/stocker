"""Closing-source authority and actual-context falsifiers; synthetic/DATA only."""
import ast
from copy import deepcopy
from dataclasses import make_dataclass
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f


def selected():
    return f.selected('P04', cursor='2022-08-31')[2][0]


def absent():
    return dict(episodes={}, slots={'1': dict(occupied_by=None, reserved_for=None)},
                cash=100., terminal_pending_terms={}, terminal_pending_sessions={},
                unresolved_terminals={}, terminal_carry_audit={}), [], dict(events=[], receivables=[])


def test_selected_closing_right_never_claims_portfolio_or_preopen_authority():
    t = selected(); f.source_cash_term(t)
    assert t['added']['cash_per_share'] == 104. and t['added']['session'] == t['actual_completion_date'] == '2022-09-30'
    assert t['source_valuation_phase'] == 'CLOSE' and t['portfolio_completion_authorized'] is False
    assert t['require_unowned_and_unordered'] is True and t['preopen_completion_confirmed'] is False
    assert t['source_capture']['run_id'] == 41798315426 and t['parent_positions'] == []


@pytest.mark.parametrize('change', ['phase', 'authority', 'unowned', 'preopen', 'cash', 'date', 'holding', 'confirmed'])
def test_source_literal_cannot_grant_earlier_or_held_cash(change):
    t = selected()
    if change == 'phase': t['source_valuation_phase'] = 'OPEN'
    elif change == 'authority': t['portfolio_completion_authorized'] = True
    elif change == 'unowned': t['require_unowned_and_unordered'] = False
    elif change == 'preopen': t['preopen_completion_confirmed'] = True
    elif change == 'cash': t['added']['cash_per_share'] = 103.
    elif change == 'date': t['added']['session'] = '2022-10-03'
    elif change == 'holding': t['parent_positions'] = [dict(quantity=1)]
    else: t['primary_extraction']['completion_confirmed_by_close'] = False
    with pytest.raises(ValueError): f.source_cash_term(t)


@pytest.mark.parametrize('change', ['episode', 'slot', 'reservation', 'order', 'object_order', 'pending', 'age', 'unresolved', 'carry', 'claim'])
def test_any_actual_ownership_order_or_claim_refuses(change):
    w, pending, ledger = absent(); sid = 'source'
    if change == 'episode': w['episodes']['1'] = dict(security_id=sid)
    elif change == 'slot': w['slots']['1']['occupied_by'] = sid
    elif change == 'reservation': w['slots']['1']['reserved_for'] = sid
    elif change == 'order': pending.append(dict(security_id=sid))
    elif change == 'object_order': pending.append(SimpleNamespace(security_id=sid))
    elif change == 'pending': w['terminal_pending_terms'][sid] = {}
    elif change == 'age': w['terminal_pending_sessions'][sid] = 0
    elif change == 'unresolved': w['unresolved_terminals'][sid] = 'missing'
    elif change == 'carry': w['terminal_carry_audit'][sid] = {}
    else: ledger['receivables'].append(dict(security_id=sid, amount=1.))
    with pytest.raises(ValueError, match='ACTUAL_UNOWNED_UNORDERED'): f.require_source_absent(w, pending, ledger, sid)


def removed_guard(name, label):
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    guard = next(n for n in ast.walk(fn) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and any(isinstance(a, ast.Constant) and a.value == label for a in n.value.args))
    for node in ast.walk(fn):
        for field in ('body', 'orelse'):
            body = getattr(node, field, None)
            if isinstance(body, list) and guard in body:
                body[body.index(guard)] = ast.Pass()
    ns = dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-source-safety-guard>', 'exec'), ns)
    return ns[name]


def test_actual_absence_guard_removal_admits_a_held_source():
    w, pending, ledger = absent(); w['episodes']['1'] = dict(security_id='source')
    with pytest.raises(ValueError): f.require_source_absent(w, pending, ledger, 'source')
    removed_guard('require_source_absent', 'FUTURE_SOURCE_ONLY_ACTUAL_UNOWNED_UNORDERED_NO_CLAIMS')(w, pending, ledger, 'source')


def test_source_authority_guard_removal_admits_portfolio_authority():
    t = selected(); t['portfolio_completion_authorized'] = True
    with pytest.raises(ValueError): f.source_cash_term(t)
    removed_guard('source_cash_term', 'OWN_INPUT_CLOSING_SOURCE_ONLY_NO_PORTFOLIO_COMPLETION_AUTHORITY')(t)


class Snapshot:
    def __init__(self, value): self.value = deepcopy(value)
    def to_dict(self): return deepcopy(self.value)


def observer(tmp_path):
    t = selected(); cp = dict(sha256=t['parent_outer_sha256'], source_cursor=t['parent_cursor'])
    material = dict(arm='P04', parent_outer_sha256=cp['sha256'], terms=[t])
    overlay = dict(add=[t['added']])
    f.save(tmp_path / f.OVERLAY, overlay)
    hydrated = tmp_path / f.hydration_name(cp); f.save(hydrated, material)
    scopes = f.source_scopes(cp, material, f.sha((tmp_path / f.OVERLAY).read_bytes()), f.sha(hydrated.read_bytes()))
    f.save(tmp_path / f.SOURCE_SCOPES, scopes)
    o = f.ActualEvents(tmp_path, 'P04', cp=cp)
    w, pending, ledger = absent()
    prior = SimpleNamespace(wealth_core=w, pending=pending, ledger=ledger, median5={'selected': [t['security_id']]})
    publication = SimpleNamespace(session=t['added']['session'])
    term = make_dataclass('SyntheticTerm', [(k, object) for k in t['added']])(**t['added'])
    return o, cp, prior, publication, term


def adapter_step(state, ledger, pending, session, terms, o):
    return o.terminal(state, terms, ledger=ledger, session=session, phase='OPEN')


def kernel_step(env, published, o):
    return o.source_values(prior=env, published=published)


def wire(o, prior, publication, terms, *, hook=None):
    o.step_code = adapter_step.__code__; o.kernel_code = kernel_step.__code__
    calls = []
    def terminal(state, terms, **kwargs):
        calls.append('terminal')
        return dict(applied=False, reason='NOT_HELD')
    def source(*, prior, published):
        calls.append('source')
        return {terms.security_id: 104.}  # Inert delegate sentinel, no return calculation.
    o.terminal_original = terminal; o.source_original = source
    def advance(run, published):
        state, ledger = Snapshot(run.state.wealth_core), Snapshot(run.state.ledger)
        adapter_step(state, ledger, run.state.pending, published.session, terms, o)
        if hook: hook(o, run, published, state, ledger)
        kernel_step(run.state, published, o)
        return SimpleNamespace(state=deepcopy(prior))
    o.advance_original = advance
    return calls


def test_actual_synthetic_advance_delegates_and_requires_two_distinct_proofs(tmp_path):
    o, cp, prior, publication, terms = observer(tmp_path)
    calls = wire(o, prior, publication, terms); before = deepcopy(vars(prior))
    o.advance(SimpleNamespace(state=prior), publication)
    assert calls == ['terminal', 'source'] and vars(prior) == before
    proof = json.loads((tmp_path / ('actual-future-event-' + publication.session + '.json')).read_bytes())
    assert proof['source_prior_absent'] is True and proof['cash'][0]['source_only_noop'] is True
    assert proof['source'][0]['original_function_delegated'] is True
    assert proof['source'][0]['scope_sha256'] == f.digest(o.scopes[0]) and proof['passed'] is True


def test_actual_prior_holding_refuses_before_any_canonical_delegate(tmp_path):
    o, cp, prior, publication, terms = observer(tmp_path); calls = wire(o, prior, publication, terms)
    prior.wealth_core['episodes']['1'] = dict(security_id=terms.security_id)
    with pytest.raises(ValueError): o.advance(SimpleNamespace(state=prior), publication)
    assert calls == []


@pytest.mark.parametrize('change', ['probe', 'mutated_prior', 'adapter_pending', 'bad_noop', 'missing_proof', 'duplicate_source', 'new_order'])
def test_actual_context_mutation_and_missing_proofs_refuse(tmp_path, change):
    o, cp, prior, publication, terms = observer(tmp_path)
    def hook(o, run, published, state, ledger):
        if change == 'probe': o.kernel_code = (lambda: None).__code__
        elif change == 'mutated_prior':
            def mutating(*, prior, published):
                prior.ledger['events'].append(dict(invalid=True)); return {terms.security_id: 104.}
            o.source_original = mutating
        elif change == 'missing_proof': o.current['cash'].clear()
        elif change == 'duplicate_source': kernel_step(run.state, published, o)
        elif change == 'new_order': prior.pending.append(dict(security_id=terms.security_id))
    calls = wire(o, prior, publication, terms, hook=hook)
    if change == 'adapter_pending':
        def bad_step(state, ledger, pending, session, terms, o):
            pending = [SimpleNamespace(security_id=terms.security_id)]
            return o.terminal(state, terms, ledger=ledger, session=session, phase='OPEN')
        o.step_code = bad_step.__code__
        o.advance_original = lambda run, published: bad_step(Snapshot(prior.wealth_core), Snapshot(prior.ledger), [], published.session, terms, o)
    elif change == 'bad_noop':
        o.terminal_original = lambda *args, **kwargs: dict(applied=True, reason='NOT_HELD')
    with pytest.raises(ValueError): o.advance(SimpleNamespace(state=prior), publication)
    assert not (tmp_path / ('actual-future-event-' + publication.session + '.json')).exists()
    if change in ('probe', 'adapter_pending'): assert 'source' not in calls


def test_kernel_frame_identity_uses_actual_env_and_published_locals():
    def kernel(env, published): return inspect.currentframe()
    prior, published = object(), object(); frame = kernel(prior, published)
    assert f.actual_source_call(frame, kernel.__code__, prior, published)
    for code, p, q in [(kernel.__code__, object(), published), (kernel.__code__, prior, object()),
                       ((lambda: None).__code__, prior, published)]:
        assert not f.actual_source_call(frame, code, p, q)


def test_kernel_code_guard_removal_allows_auxiliary_probe():
    def kernel(env, published): return inspect.currentframe()
    prior, published = object(), object(); frame = kernel(prior, published); wrong = (lambda: None).__code__
    assert not f.actual_source_call(frame, wrong, prior, published)
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'actual_source_call')
    fn.body[0].value.values.pop(0); ns = dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-kernel-code-guard>', 'exec'), ns)
    assert ns['actual_source_call'](frame, wrong, prior, published)


@pytest.mark.parametrize('field', ['overlay_sha256', 'hydrated_sha256', 'terminal_sha256', 'parent_outer_sha256', 'parent_root_admission_sha256', 'portfolio_completion_authorized'])
def test_retained_scope_cannot_change_or_grant_portfolio_authority(tmp_path, field):
    o, cp, prior, publication, terms = observer(tmp_path)
    raw = json.loads((tmp_path / f.SOURCE_SCOPES).read_bytes())
    raw[0][field] = True if field == 'portfolio_completion_authorized' else '0' * 64
    (tmp_path / f.SOURCE_SCOPES).write_text(json.dumps(raw))
    with pytest.raises(ValueError): f.ActualEvents(tmp_path, 'P04', cp=cp)


def test_real_overlay_cannot_omit_explicit_parent_or_scope(tmp_path):
    o, cp, prior, publication, terms = observer(tmp_path)
    with pytest.raises(ValueError): f.ActualEvents(tmp_path, 'P04')
    (tmp_path / f.SOURCE_SCOPES).unlink()
    with pytest.raises(FileNotFoundError): f.ActualEvents(tmp_path, 'P04', cp=cp)


@pytest.mark.parametrize('change', ['drop', 'reclassify', 'numeric_false'])
def test_source_scope_cannot_be_silently_disabled_or_type_changed(tmp_path, change):
    o, cp, prior, publication, terms = observer(tmp_path)
    if change == 'numeric_false':
        path = tmp_path / f.SOURCE_SCOPES
        value = json.loads(path.read_bytes()); value[0]['portfolio_completion_authorized'] = 0
    else:
        path = tmp_path / f.hydration_name(cp)
        value = json.loads(path.read_bytes())
        if change == 'drop': value['terms'].clear()
        else: value['terms'][0]['recognition_rule'] = f.NEXT_COMPLETION
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError): f.ActualEvents(tmp_path, 'P04', cp=cp)


def test_post_advance_source_order_refuses_before_journal_commit(tmp_path):
    o, cp, prior, publication, terms = observer(tmp_path); wire(o, prior, publication, terms)
    delegate = o.advance_original
    def advance(run, published):
        result = delegate(run, published)
        result.state.pending.append(dict(security_id=terms.security_id))
        return result
    o.advance_original = advance
    with pytest.raises(ValueError): o.advance(SimpleNamespace(state=prior), publication)


def test_actual_phase_guard_removal_accepts_missing_source_proof():
    w, pending, ledger = absent()
    result = SimpleNamespace(state=SimpleNamespace(wealth_core=w, pending=pending, ledger=ledger))
    record = dict(session='day', source_prior_absent=True, source=[], cash=[])
    scopes = [dict(session='day', security_id='source')]
    with pytest.raises(ValueError): f.actual_source_phase(record, result, scopes)
    removed_guard('actual_source_phase', 'FUTURE_SOURCE_ONLY_ONE_ACTUAL_NOOP_AND_SOURCE_DELEGATION')(record, result, scopes)
