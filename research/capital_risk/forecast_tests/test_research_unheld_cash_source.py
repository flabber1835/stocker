"""Independent AST/input qualification; synthetic observers, no financial imports."""
import ast, csv, gzip, hashlib, importlib, inspect, io, json, math, os, re, sys
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, is_dataclass, make_dataclass
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal
from zoneinfo import ZoneInfo
import zipfile
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError
P = Path(__file__).parent
C = Path(os.environ.get('UNHELD_CASH_SOURCE_DIR', str(P.parent)))
FUTURE = C / 'system_campaign_financial_future.py'
CATALOG = C / 'system-campaign-selected-own-cash-terminal-facts.json'
if (P.parent.parent / 'future-after-v2.py').exists():
    FUTURE = P.parent.parent / 'future-after-v2.py'
    CATALOG = P.parent.parent / 'catalog30.json'
sha = lambda raw: hashlib.sha256(raw).hexdigest()
enc = lambda value: (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
digest = lambda value: sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())

def need(value, code):
    if not value:
        raise ValueError(code)

def read(path):
    return Path('\\\\?\\' + str(Path(path).resolve())).read_bytes()

class Fence:

    def find_spec(self, name, path=None, target=None):
        if name.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('UNHELD_CASH_INPUT_FENCE:' + name)

@pytest.fixture(autouse=True)
def fence():
    guard = Fence()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)

class Files:

    def __truediv__(self, name):
        return CATALOG if name == 'system-campaign-selected-own-cash-terminal-facts.json' else C / name

class Transform(ast.NodeTransformer):

    def __init__(self, remove):
        self.remove = remove

    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and (node.value.func.id == 'need') and any((isinstance(v, ast.Constant) and v.value == self.remove for v in node.value.args)):
            return ast.Pass()
        return self.generic_visit(node)

def load(*, before=False, remove=None):
    path = FUTURE
    tree = ast.parse(path.read_bytes())
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom)) and (not (isinstance(n, ast.Assign) and any((isinstance(t, ast.Name) and t.id == 'HERE' for t in n.targets))))]
    tree = Transform(remove).visit(tree)
    ns = dict(__file__=str(path), HERE=Files(), Path=Path, json=json, math=math, sha=sha, digest=digest, need=need, deepcopy=deepcopy, SimpleNamespace=SimpleNamespace, Fraction=Fraction, BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, Annotated=Annotated, Literal=Literal, asdict=asdict, is_dataclass=is_dataclass, zipfile=zipfile, inspect=inspect, date=date, datetime=datetime, ZoneInfo=ZoneInfo, hosted=lambda: None, save=lambda p, v: p.write_bytes(enc(v)), importlib=importlib)
    exec(compile(ast.fix_missing_locations(tree), '<input-only-unheld-cash>', 'exec'), ns)
    return ns

@pytest.fixture
def data():
    fixture = json.loads((P / 'fixtures/unheld-cash-source.json').read_bytes())
    n = load()
    catalog = json.loads(CATALOG.read_bytes())
    rootbundle = json.loads((C / 'system-campaign-financial-admitted-parents.json').read_bytes())

    def root_spec(arm, pin=None):
        e = rootbundle['arms'][arm]
        if pin is not None and e['admission_sha256'] != pin:
            e = rootbundle['historical_roots'][pin]
        return dict(deepcopy(e['transport']), root_admission=e['admission'], root_admission_sha256=e['admission_sha256'])
    n.update(root_spec=root_spec, validate_term=lambda term: None, calendar=SimpleNamespace(__file__=str(C / 'system_campaign_cash_calendar.py')))
    return (n, deepcopy(fixture['new_term']), fixture, catalog)

def test_original_and_all29_old_records_preserved(data):
    n, t, f, catalog = data
    assert sha(enc(dict(deepcopy(catalog), terms=catalog['terms'][:29]))) == f['previous_catalog_sha256']
    raw = (C / 'p01_factual_batch_facts.json').read_bytes()
    assert sha(raw) == f['original_legal_catalog_sha256'] == t['retained_original_legal_record']['sha256']
    original, = [r for r in json.loads(raw)['records'] if digest(r) == t['retained_original_legal_record']['record_sha256']]
    assert original == f['original_legal_record']
    assert (original['cash_per_share'], original['economic_session'], original['clock_scope'], original['held_representation_scope'], original['source_pending_scope']) == ('55.50', '2021-11-30', 'DAILY_MARKET_UNHELD_SOURCE', 'SOURCE_UNHELD', 'REFUSE_ALL_SOURCE_INTENTS')
    n['research_unheld_cash_term'](t)

@pytest.mark.parametrize('field,value', [('closing_availability_assumed', False), ('completion_confirmed_by_close', True), ('actual_settlement_claimed', True), ('portfolio_completion_authorized', True), ('published_cash_per_share', 55.5), ('extra', 'unqualified')])
def test_typed_assumption_rejects_upgrade(data, field, value):
    n, t, f, c = data
    t['research_assumption'][field] = value
    with pytest.raises((ValueError, ValidationError)):
        n['research_unheld_cash_term'](t)

@pytest.mark.parametrize('mutation', ['amount', 'native', 'sid', 'identity', 'date', 'original_record', 'original_catalog', 'held', 'preopen', 'mandatory', 'byclose', 'authority', 'phase'])
def test_original_scope_and_cash_guards(data, mutation):
    n, t, f, c = data
    if mutation == 'amount':
        t['added']['cash_per_share'] = 56.0
    if mutation == 'native':
        t['native_term_sha256'] = '0' * 64
    if mutation == 'sid':
        t['security_id'] = 'other'
    if mutation == 'identity':
        t['identity_witness']['ticker'] = 'OTHER'
    if mutation == 'date':
        t['added']['session'] = '2021-12-01'
    if mutation == 'original_record':
        t['retained_original_legal_record']['record_sha256'] = '0' * 64
    if mutation == 'original_catalog':
        t['retained_original_legal_record']['sha256'] = '0' * 64
    if mutation == 'held':
        t['parent_positions'] = [dict(quantity=1)]
    if mutation == 'preopen':
        t['preopen_completion_confirmed'] = True
    if mutation == 'mandatory':
        t['mandatory_common_share_completion_confirmed'] = True
    if mutation == 'byclose':
        t['completion_confirmed_by_close'] = True
    if mutation == 'authority':
        t['portfolio_completion_authorized'] = True
    if mutation == 'phase':
        t['source_valuation_phase'] = 'OPEN'
    with pytest.raises((ValueError, ValidationError)):
        n['research_unheld_cash_term'](t)

def dates():
    # Tiny synthetic trading axis; the independent private review checks the actual frozen axis.
    return ['2021-11-24', '2021-11-26', '2021-11-29', '2021-11-30', '2021-12-01']

def test_strict_frozen_axis(data):
    n, t, f, c = data
    axis = dates()
    n['completion_session'](t, axis)
    assert axis[axis.index('2021-11-29') + 1] == '2021-11-30'
    for bad in [axis[::-1], axis + [axis[-1]], [d for d in axis if d != '2021-11-26'], [d for d in axis if d != '2021-11-30']]:
        with pytest.raises(ValueError):
            n['completion_session'](t, bad)

def test_old_source_close_and_source_scope_ast_unchanged(data):
    n, t, f, c = data
    nodes = {v.name: ast.dump(v, include_attributes=False) for v in ast.parse(FUTURE.read_bytes()).body if isinstance(v, (ast.ClassDef, ast.FunctionDef))}
    assert all(sha(nodes[key].encode()) == pin for key, pin in f['protected_ast_sha256'].items())


def source_setup(data):
    n, t, f, c = data
    cp = dict(sha256=t['parent_outer_sha256'], source_cursor=t['parent_cursor'])
    material = dict(arm='P05', parent_outer_sha256=cp['sha256'], terms=[deepcopy(t)])
    n['selected'] = lambda arm, cursor: (None, None, [deepcopy(t)])
    return (n, t, cp, material)

def test_source_scope_is_mandatory_and_close_only(data):
    n, t, cp, m = source_setup(data)
    scope, = n['source_scopes'](cp, m, 'a' * 64, 'b' * 64)
    assert scope['portfolio_completion_authorized'] is False and scope['require_unowned_and_unordered'] is True
    assert scope['source_valuation_phase'] == 'CLOSE' and scope['terminal_sha256'] == digest(t['added'])
    assert 'require_never_held' not in scope

@pytest.mark.parametrize('mutation', ['omit', 'reclassify', 'extra', 'root', 'arm', 'cursor'])
def test_scope_omission_reclassification_and_root_refuse(data, mutation):
    n, t, cp, m = source_setup(data)
    if mutation == 'omit':
        m['terms'] = []
    if mutation == 'reclassify':
        m['terms'][0]['recognition_rule'] = n['RESEARCH_CASH']
    if mutation == 'extra':
        m['terms'].append(deepcopy(t))
    if mutation == 'root':
        cp['sha256'] = '0' * 64
    if mutation == 'arm':
        m['arm'] = 'P11'
    if mutation == 'cursor':
        cp['source_cursor'] = '2021-11-30'
    with pytest.raises(ValueError):
        n['source_scopes'](cp, m, 'a' * 64, 'b' * 64)

def test_source_scope_strict_model(data):
    n, t, cp, m = source_setup(data)
    scope, = n['source_scopes'](cp, m, 'a' * 64, 'b' * 64)
    for field, value in [('source_valuation_phase', 'OPEN'), ('portfolio_completion_authorized', True), ('require_unowned_and_unordered', False), ('extra', 'x')]:
        bad = dict(scope, **{field: value})
        with pytest.raises(ValidationError):
            n['SourceOnlyScope'].model_validate(bad)

def absent():
    return (dict(episodes={}, slots={'0': dict(occupied_by=None, reserved_for=None)}, cash=100.0, terminal_pending_terms={}, terminal_pending_sessions={}, unresolved_terminals={}, terminal_carry_audit={}), [], dict(events=[], receivables=[]))

@pytest.mark.parametrize('kind', ['episode', 'occupied', 'reserved', 'intent', 'object_intent', 'pending_term', 'pending_session', 'unresolved', 'carry', 'claim'])
def test_every_actual_absence_predicate(data, kind):
    n, t, f, c = data
    wealth, pending, ledger = absent()
    sid = t['security_id']
    n['require_source_absent'](wealth, pending, ledger, sid)
    if kind == 'episode':
        wealth['episodes']['0'] = dict(security_id=sid)
    if kind == 'occupied':
        wealth['slots']['0']['occupied_by'] = sid
    if kind == 'reserved':
        wealth['slots']['0']['reserved_for'] = sid
    if kind == 'intent':
        pending.append(dict(security_id=sid))
    if kind == 'object_intent':
        pending.append(SimpleNamespace(security_id=sid))
    if kind == 'pending_term':
        wealth['terminal_pending_terms'][sid] = {}
    if kind == 'pending_session':
        wealth['terminal_pending_sessions'][sid] = 0
    if kind == 'unresolved':
        wealth['unresolved_terminals'][sid] = {}
    if kind == 'carry':
        wealth['terminal_carry_audit'][sid] = {}
    if kind == 'claim':
        ledger['receivables'].append(dict(security_id=sid))
    with pytest.raises(ValueError, match='ACTUAL_UNOWNED_UNORDERED_NO_CLAIMS'):
        n['require_source_absent'](wealth, pending, ledger, sid)

def test_no_invented_never_held_requirement(data):
    n, t, f, c = data
    wealth, pending, ledger = absent()
    ledger['events'] = [dict(security_id=t['security_id'], event_type='HISTORICAL_SELL')]
    n['require_source_scope'](wealth, pending, ledger, dict(security_id=t['security_id']))

def observer_setup(data, tmp_path):
    n, t, cp, material = source_setup(data)
    scope, = n['source_scopes'](cp, material, 'a' * 64, 'b' * 64)
    observer = object.__new__(n['ActualEvents'])
    observer.out = tmp_path
    observer.arm = 'P05'
    observer.terms = {(t['added']['session'], t['security_id']): deepcopy(t['added'])}
    observer.scopes = [scope]
    observer.saved = []
    observer.current = dict(session=t['added']['session'], cash=[], stock=[], source=[], order=[], source_prior_absent=True)
    wealth, pending, ledger = absent()

    class State:

        def __init__(self, value):
            self.value = deepcopy(value)

        def to_dict(self):
            return deepcopy(self.value)

    class Ledger(State):
        pass
    state, book = (State(wealth), Ledger(ledger))
    Native = make_dataclass('SyntheticTerminal', [(key, object) for key in t['added']])
    term = Native(**t['added'])
    calls = []

    def original_terminal(state, term, **kwargs):
        calls.append(('terminal', asdict(term)))
        return dict(applied=False, reason='NOT_HELD')

    def step(state, ledger, pending, session, observer, term):
        return observer.terminal(state, term, ledger=ledger, phase='OPEN')

    def kernel(env, published, observer):
        return observer.source_values(prior=env, published=published)
    observer.terminal_original = original_terminal
    observer.step_code = step.__code__
    observer.kernel_code = kernel.__code__
    prior = SimpleNamespace(wealth_core=deepcopy(wealth), pending=[], ledger=deepcopy(ledger), median5=dict(selected=[t['security_id']]))
    published = SimpleNamespace(session=t['added']['session'])
    result = {t['security_id']: 123.456}

    def original_source(*, prior, published):
        calls.append(('source',))
        return result
    observer.source_original = original_source
    return (n, t, scope, observer, state, book, pending, step, kernel, prior, published, calls, result)

def test_actual_synthetic_adapter_noop_then_source_delegation(data, tmp_path):
    n, t, scope, o, state, book, pending, step, kernel, prior, published, calls, result = observer_setup(data, tmp_path)
    before = deepcopy((state.to_dict(), book.to_dict(), prior.__dict__))
    term = make_dataclass('T', [(key, object) for key in t['added']])(**t['added'])
    assert step(state, book, pending, t['added']['session'], o, term) == dict(applied=False, reason='NOT_HELD')
    assert kernel(prior, published, o) is result
    assert calls == [('terminal', t['added']), ('source',)]
    assert o.current['cash'][0]['source_only_noop'] is True
    assert o.current['cash'][0]['postcondition'] == dict(actual_held=False, quantity=0, nominal_cash=0.0)
    n['actual_source_phase'](o.current, SimpleNamespace(state=prior), [scope])
    assert before == (state.to_dict(), book.to_dict(), prior.__dict__)

@pytest.mark.parametrize('kind', ['direct_terminal', 'missing_absence', 'terminal_mutation', 'terminal_applied', 'source_direct', 'source_mutation', 'source_missing_value'])
def test_observer_refuses_fabrication_or_mutation(data, tmp_path, kind):
    n, t, scope, o, state, book, pending, step, kernel, prior, published, calls, result = observer_setup(data, tmp_path)
    term = make_dataclass('T', [(key, object) for key in t['added']])(**t['added'])
    if kind == 'direct_terminal':
        action = lambda: o.terminal(state, term, ledger=book, phase='OPEN')
    if kind == 'missing_absence':
        o.current['source_prior_absent'] = False
        action = lambda: step(state, book, pending, t['added']['session'], o, term)
    if kind == 'terminal_mutation':

        def bad(*args, **kwargs):
            book.value['events'].append(dict(unqualified=True))
            return dict(applied=False, reason='NOT_HELD')
        o.terminal_original = bad
        action = lambda: step(state, book, pending, t['added']['session'], o, term)
    if kind == 'terminal_applied':
        o.terminal_original = lambda *a, **k: dict(applied=True, reason='NOT_HELD')
        action = lambda: step(state, book, pending, t['added']['session'], o, term)
    if kind == 'source_direct':
        action = lambda: o.source_values(prior=prior, published=published)
    if kind == 'source_mutation':

        def bad(*, prior, published):
            prior.pending.append(dict(security_id=t['security_id']))
            return result
        o.source_original = bad
        action = lambda: kernel(prior, published, o)
    if kind == 'source_missing_value':
        o.source_original = lambda **kwargs: {}
        action = lambda: kernel(prior, published, o)
    with pytest.raises(ValueError):
        action()

def test_source_phase_requires_exactly_one_real_call_each(data, tmp_path):
    n, t, scope, o, *_ = observer_setup(data, tmp_path)
    prior = SimpleNamespace(wealth_core=absent()[0], pending=[], ledger=absent()[2])
    for record in [o.current, dict(o.current, source=[dict(security_id=t['security_id'], actual_context_call=True)])]:
        with pytest.raises(ValueError, match='ONE_ACTUAL_NOOP_AND_SOURCE_DELEGATION'):
            n['actual_source_phase'](record, SimpleNamespace(state=prior), [scope])

def calendar_module(n):
    path = C / 'system_campaign_cash_calendar.py'
    tree = ast.parse(path.read_bytes())
    ns = dict(__file__=str(path), Path=Path, json=json, need=need, sha=sha, digest=digest, deepcopy=deepcopy, math=math)
    safe = [v for v in tree.body if isinstance(v, (ast.FunctionDef, ast.ClassDef, ast.Assign))]
    exec(compile(ast.fix_missing_locations(Transform(None).visit(ast.Module(body=safe, type_ignores=[]))), '<original-calendar-input>', 'exec'), ns)
    registry = (C / 'system_campaign_ordinary_registry.py').read_bytes()
    registry_tree = ast.parse(registry)
    registry_nodes = [v for v in registry_tree.body if isinstance(v, ast.Assign) or (isinstance(v, ast.FunctionDef) and v.name == 'registrations')]
    registry_ns = dict(Path=Path, json=json, re=re, need=need)
    exec(compile(ast.fix_missing_locations(ast.Module(body=registry_nodes, type_ignores=[])), '<original-bounded-registry>', 'exec'), registry_ns)
    ns['registrations'] = lambda: registry_ns['registrations'](C)
    n['importlib'] = SimpleNamespace(import_module=lambda module: SimpleNamespace(__file__=str(path), CashCalendar=ns['CashCalendar']))

def test_original_december_eight_composition(data):
    n, t, f, c = data
    calendar_module(n)
    terms, sources = n['supplemental_selection']('P05', '2021-10-29')
    assert [v['ticker'] for v in terms] == ['COR2', 'DRNA', 'ARNA', 'EPAY', 'CCXI1', 'NEWR', 'IMGN', 'CTLT']
    assert len(sources) == 1
    assert all((v['native_session'] > '2021-10-29' for v in terms))
    merged = n['merge_selected_terms']([t], terms)
    assert len(merged) == 9 and merged[0] == t
    with pytest.raises(ValueError):
        n['merge_selected_terms'](merged, [t])

@pytest.mark.parametrize('name', ['research.pooled_vacancy_funding', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError, match='FENCE'):
        importlib.import_module(name)

@pytest.mark.parametrize('label,mutation', [('OWN_INPUT_UNHELD_EXACT_ORIGINAL_CATALOG_BYTES', 'catalog'), ('OWN_INPUT_UNHELD_ORIGINAL_RECORD_AND_SCOPE', 'native'), ('OWN_INPUT_UNHELD_RESEARCH_CLOSING_CASH_AND_IDENTITY', 'amount'), ('OWN_INPUT_UNHELD_NO_PORTFOLIO_COMPLETION_AUTHORITY', 'held'), ('OWN_INPUT_UNHELD_RESEARCH_EXACT_NEXT_FROZEN_BOUNDARY', 'axis')])
def test_new_input_guard_removals_detected(data, label, mutation):
    original, t, f, c = data
    n = load(remove=label)
    if mutation == 'catalog':
        t['retained_original_legal_record']['sha256'] = '0' * 64
    if mutation == 'native':
        t['native_term_sha256'] = '0' * 64
    if mutation == 'amount':
        t['added']['cash_per_share'] = 56.0
        t['research_assumption']['published_cash_per_share'] = '56.00'
    if mutation == 'held':
        t['parent_positions'] = [dict(quantity=1)]
    if mutation == 'axis':
        bad = [d for d in dates() if d != '2021-11-26']
        with pytest.raises(ValueError):
            original['completion_session'](t, bad)
        n['completion_session'](t, bad)
    else:
        with pytest.raises(ValueError):
            original['research_unheld_cash_term'](t)
        n['research_unheld_cash_term'](t)

@pytest.mark.parametrize('label,mutation', [('FUTURE_SOURCE_ONLY_SCOPE_CANNOT_BE_OMITTED_OR_RECLASSIFIED', 'omit'), ('FUTURE_SOURCE_ONLY_EXACT_OWN_ADMITTED_PARENT_AND_LITERAL', 'root')])
def test_source_scope_guard_removals_detected(data, label, mutation):
    original, t, cp, m = source_setup(data)
    n = load(remove=label)
    n.update(selected=original['selected'], root_spec=original['root_spec'])
    if mutation == 'omit':
        m['terms'] = []
    if mutation == 'root':
        cp['sha256'] = '0' * 64
        m['parent_outer_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        original['source_scopes'](cp, m, 'a' * 64, 'b' * 64)
    result = n['source_scopes'](cp, m, 'a' * 64, 'b' * 64)
    assert result == [] if mutation == 'omit' else result[0]['parent_outer_sha256'] == '0' * 64

def test_absence_guard_removal_detected(data):
    original, t, f, c = data
    n = load(remove='FUTURE_SOURCE_ONLY_ACTUAL_UNOWNED_UNORDERED_NO_CLAIMS')
    wealth, pending, ledger = absent()
    wealth['episodes']['0'] = dict(security_id=t['security_id'])
    with pytest.raises(ValueError):
        original['require_source_absent'](wealth, pending, ledger, t['security_id'])
    n['require_source_absent'](wealth, pending, ledger, t['security_id'])

def test_source_readonly_guard_removal_detected(data, tmp_path):
    original, t, scope, o, state, book, pending, step, kernel, prior, published, calls, result = observer_setup(data, tmp_path)

    def mutation(*, prior, published):
        prior.ledger['events'].append(dict(unqualified=True))
        return result
    o.source_original = mutation
    with pytest.raises(ValueError):
        kernel(prior, published, o)
    prior.ledger['events'] = []
    mutant = load(remove='FUTURE_SOURCE_ONLY_ORIGINAL_RETURN_FUNCTION_READONLY')
    o.source_values = mutant['ActualEvents'].source_values.__get__(o)
    assert kernel(prior, published, o) is result

def test_exact_noop_guard_removal_detected(data, tmp_path):
    original, t, scope, o, state, book, pending, step, kernel, prior, published, calls, result = observer_setup(data, tmp_path)
    term = make_dataclass('T', [(key, object) for key in t['added']])(**t['added'])
    o.terminal_original = lambda *args, **kwargs: dict(applied=True, reason='NOT_HELD')
    with pytest.raises(ValueError):
        step(state, book, pending, t['added']['session'], o, term)
    mutant = load(remove='FUTURE_SOURCE_ONLY_CANONICAL_TERMINAL_EXACT_NOOP')
    o.terminal = mutant['ActualEvents'].terminal.__get__(o)
    assert step(state, book, pending, t['added']['session'], o, term)['applied'] is True

def test_delegate_count_guard_removal_detected(data, tmp_path):
    original, t, scope, o, *_ = observer_setup(data, tmp_path)
    prior = SimpleNamespace(wealth_core=absent()[0], pending=[], ledger=absent()[2])
    with pytest.raises(ValueError):
        original['actual_source_phase'](o.current, SimpleNamespace(state=prior), [scope])
    mutant = load(remove='FUTURE_SOURCE_ONLY_ONE_ACTUAL_NOOP_AND_SOURCE_DELEGATION')
    mutant['actual_source_phase'](o.current, SimpleNamespace(state=prior), [scope])

def test_literal_selection_current_root_guard_removal_detected(data):
    original, t, f, c = data
    historical = dict(deepcopy(c), terms=deepcopy(c['terms'][:30]))
    assert sha(enc(historical)) == '5951b1ffa420910291a756b31b0a9a324ace68f4af77c854a9cc71a71b3115a5'
    phases = {(row['arm'], row['parent_cursor']) for row in historical['terms']}
    def exact_historical_metadata(namespace):
        # Isolate the original catalog30 root-scope guard. Production guards stay intact.
        for name in ('OWN_CASH_PHASES', 'OWN_CASH_SOURCE_CLOCKS', 'CASH_GENERATION_LENGTHS'):
            namespace[name] = {key: value for key, value in namespace[name].items() if key in phases}
        namespace['CLOSED_CASH_GENERATIONS'] = {key: count for key, count in namespace['CLOSED_CASH_GENERATIONS'].items() if count < 30}
    exact_historical_metadata(original)
    bad = deepcopy(historical)
    bad['terms'][-1]['parent_outer_sha256'] = '0' * 64
    raw = enc(bad)

    class ChangedFiles:

        def __truediv__(self, name):
            return SimpleNamespace(read_bytes=lambda: raw) if name == original['OWN_CASH_CATALOG'] else C / name
    original['HERE'] = ChangedFiles()
    original['OWN_CASH_SHA'] = sha(raw)
    with pytest.raises(ValueError, match='CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'):
        original['own_cash_selection']('P05', '2021-10-29')
    mutant = load(remove='OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE')
    exact_historical_metadata(mutant)
    mutant.update(HERE=ChangedFiles(), OWN_CASH_SHA=sha(raw), root_spec=original['root_spec'], validate_term=original['validate_term'], calendar=original['calendar'])
    assert mutant['own_cash_selection']('P05', '2021-10-29')[2][0]['parent_outer_sha256'] == '0' * 64

def test_source_close_still_requires_actual_byclose_confirmation(data):
    n, t, f, c = data
    old = deepcopy(t)
    old.update(recognition_rule=n['SOURCE_CLOSE'], mandatory_common_share_completion_confirmed=True, primary_extraction=dict(actual_completion_date=t['actual_completion_date'], cash_per_ordinary_common_share='55.50', mandatory_conversion=True, preopen_time_established=False, completion_confirmed_by_close=False, recognition_convention=n['SOURCE_CLOSE']))
    with pytest.raises(ValueError, match='CLOSING_SOURCE_ONLY_NO_PORTFOLIO_COMPLETION_AUTHORITY'):
        n['source_cash_term'](old)
    old['primary_extraction']['completion_confirmed_by_close'] = True
    n['source_cash_term'](old)
    n['research_unheld_cash_term'](t)
    assert t['mandatory_common_share_completion_confirmed'] is False
    assert t['portfolio_completion_authorized'] is False

def supplemental_double(n, mutate=lambda catalog: None):
    path = C / 'system_campaign_cash_calendar.py'

    class ConstructorDouble:

        def __init__(self, catalog):
            self.catalog = deepcopy(catalog)
            mutate(self.catalog)
    n['importlib'] = SimpleNamespace(import_module=lambda module: SimpleNamespace(__file__=str(path), CashCalendar=ConstructorDouble))

def test_same_day_optin_does_not_authorize_foreign_phase(data):
    n, t, f, c = data
    supplemental_double(n)
    n['SUPPLEMENTAL_PHASES']['P05', '2021-10-30'] = n['SUPPLEMENTAL_PHASES']['P05', '2021-10-29']
    with pytest.raises(ValueError, match='ONLY_UNCONSUMED_TERMS'):
        n['supplemental_selection']('P05', '2021-10-30')

@pytest.mark.parametrize('mutation', ['unconfirmed', 'noncash', 'wrongrule', 'consumed', 'reverse'])
def test_same_day_optin_still_refuses_unqualified_terms(data, mutation):
    n, t, f, c = data

    def change(catalog):
        term = next((t for t in catalog['terms'] if t['ticker'] == 'ARNA'))
        if mutation == 'unconfirmed':
            term['preopen_completion_confirmed'] = False
        if mutation == 'noncash':
            term['added']['kind'] = 'CASH_PLUS_STOCK'
        if mutation == 'wrongrule':
            term['recognition_rule'] = 'RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY'
        if mutation == 'consumed':
            term['native_session'] = '2021-10-29'
        if mutation == 'reverse':
            term['added']['session'] = '2022-03-10'
    supplemental_double(n, change)
    with pytest.raises(ValueError, match='EXPLICIT_ORIGINAL_SAME_DAY_PREOPEN_CASH_ONLY'):
        n['supplemental_selection']('P05', '2021-10-29')

def test_new_same_day_guard_removal_detected(data):
    original, t, f, c = data

    def change(catalog):
        next((t for t in catalog['terms'] if t['ticker'] == 'ARNA'))['preopen_completion_confirmed'] = False
    supplemental_double(original, change)
    with pytest.raises(ValueError):
        original['supplemental_selection']('P05', '2021-10-29')
    mutant = load(remove='FUTURE_SUPPLEMENT_EXPLICIT_ORIGINAL_SAME_DAY_PREOPEN_CASH_ONLY')
    supplemental_double(mutant, change)
    terms, sources = mutant['supplemental_selection']('P05', '2021-10-29')
    assert next((t for t in terms if t['ticker'] == 'ARNA'))['preopen_completion_confirmed'] is False

def test_foreign_phase_strict_guard_ast_preserved():
    node = next(n for n in ast.walk(ast.parse(FUTURE.read_bytes())) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'need' and any(isinstance(a, ast.Constant) and a.value == 'FUTURE_SUPPLEMENT_ONLY_UNCONSUMED_TERMS' for a in n.args))
    assert sha(ast.dump(node, include_attributes=False).encode()) == 'a99c477153def40d64e68f9ef5af38be2cfbaea056dc54307d099decf13b2dbf'
