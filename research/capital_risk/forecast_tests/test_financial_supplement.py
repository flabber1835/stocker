"""Interleaved original inputs and source guards; no financial execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_source_close import removed_guard


@pytest.mark.parametrize('arm,cursor,tickers', [
    ('P03', '2018-11-30', ['ARII','OCLR','APTI','VSM','MZOR','TSRO','ZAYO','XOXO','MB2','ESRX']),
    ('P05', '2018-11-30', ['APTI', 'VSM', 'OCLR', 'MZOR', 'TSRO', 'ZAYO', 'XOXO', 'MB2', 'ESRX']),
    ('P07', '2021-03-31', ['MIK', 'VAR', 'NAV', 'WORK', 'HOME', 'TRIL1',
                         'FPRX', 'GNMK', 'GLUU', 'WIFI', 'PFPT', 'STMP', 'NUAN', 'CERN']),
])
def test_actual_hydration_source_composition_covers_interleaved_events(tmp_path, arm, cursor, tickers):
    codec, catalog, terms = f.selected(arm, cursor=cursor)
    tree = ast.parse(Path(f.__file__).read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'hydrate')
    start = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'ordinary_components' for t in n.targets))
    end = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Expr)
               and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
               and n.value.func.id == 'suppressions')
    scope = dict(vars(f), arm=arm, cp=dict(source_cursor=cursor, repairs=[]), source_root=tmp_path,
                 codec=codec, catalog=catalog, terms=deepcopy(terms))
    exec(compile(ast.fix_missing_locations(ast.Module(body=fn.body[start:end+1], type_ignores=[])),
                 '<actual-data-only-source-composition>', 'exec'), scope)
    assert [t['ticker'] for t in scope['terms']] == tickers
    assert len(scope['ordinary_components']) == (1 if arm == 'P07' else 3)
    assert scope['inherited_ordinary'] == []
    if arm == 'P05':
        by = {t['ticker']: t for t in scope['terms']}
        assert by['MZOR']['added']['session'] < by['APTI']['native_session']
        assert by['MZOR']['added']['cash_per_share'] == 58.5
        assert by['ESRX']['added']['exchange_ratio'] == .2434
        assert by['ESRX']['added']['delivered_ticker'] == 'CI'
        assert by['XOXO']['added']['session'] == by['ESRX']['added']['session'] == '2018-12-21'
    elif arm == 'P07':
        original = json.loads((f.HERE / 'system-campaign-future-input-amendment-catalog.json').read_bytes())
        for term, saved in zip(scope['terms'][6:], original['terms']):
            assert term['identity_witness'] == saved['identity_witness']
            assert term['added'] == saved['added']
    else:
        assert terms[0]['ticker']=='ARII' and terms[0]['source_capture']['run_id']==41934413763
        assert not any(t['ticker']=='AET'for t in scope['terms'])
        assert all(t['native_session']>cursor for t in scope['terms'])
        assert len({s['catalog_file']for s in scope['ordinary_components']})==3


def test_literal_witness_survives_actual_frozen_date_normalization():
    terms, _ = f.supplemental_selection('P07', '2021-03-31')
    before = deepcopy(terms)
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == 'hydrate')
    node = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign) and isinstance(n.value, ast.ListComp)
                and any(isinstance(t, ast.Name) and t.id == 'terms' for t in n.targets))
    scope = dict(vars(f), terms=terms, dates=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<actual-data-only-date-normalization>', 'exec'), scope)
    assert scope['terms'] == before


def test_exact_catalog_and_validator_bytes_falsifier(tmp_path, monkeypatch):
    plan = f.SUPPLEMENTAL_PHASES['P05', '2018-11-30'][0]
    for source in f.SUPPLEMENTAL_PHASES['P05', '2018-11-30']:
        (tmp_path / source[3]).write_bytes((f.HERE / source[3]).read_bytes())
    (tmp_path / plan[3]).write_bytes((f.HERE / plan[3]).read_bytes() + b'\n')
    monkeypatch.setattr(f, 'HERE', tmp_path)
    with pytest.raises(ValueError, match='SUPPLEMENT_EXACT_ORIGINAL_SOURCE_BYTES'):
        f.supplemental_selection('P05', '2018-11-30')
    assert len(removed_guard('supplemental_selection',
        'FUTURE_SUPPLEMENT_EXACT_ORIGINAL_SOURCE_BYTES')('P05', '2018-11-30')[0]) == 6


def test_constructor_guard_falsifier(monkeypatch):
    plan, = f.SUPPLEMENTAL_PHASES['P07', '2021-03-31']
    changed = (*plan[:2], 'UNDECLARED', *plan[3:])
    monkeypatch.setitem(f.SUPPLEMENTAL_PHASES, ('P07', '2021-03-31'), (changed,))
    with pytest.raises(ValueError, match='SUPPLEMENT_DECLARED_CONSTRUCTOR'):
        f.supplemental_selection('P07', '2021-03-31')
    assert len(removed_guard('supplemental_selection',
        'FUTURE_SUPPLEMENT_DECLARED_CONSTRUCTOR')('P07', '2021-03-31')[0]) == 8


def test_consumed_native_guard_falsifier(monkeypatch):
    plans = f.SUPPLEMENTAL_PHASES['P07', '2021-03-31']
    monkeypatch.setitem(f.SUPPLEMENTAL_PHASES, ('P07', '2021-04-15'), plans)
    with pytest.raises(ValueError, match='SUPPLEMENT_ONLY_UNCONSUMED_TERMS'):
        f.supplemental_selection('P07', '2021-04-15')
    assert len(removed_guard('supplemental_selection',
        'FUTURE_SUPPLEMENT_ONLY_UNCONSUMED_TERMS')('P07', '2021-04-15')[0]) == 8


def test_duplicate_source_guard_falsifier(monkeypatch):
    plan, = f.SUPPLEMENTAL_PHASES['P07', '2021-03-31']
    plans = ((*plan[:-1], ('FPRX',)), (*plan[:-1], ('GNMK',)))
    monkeypatch.setitem(f.SUPPLEMENTAL_PHASES, ('P07', '2021-03-31'), plans)
    with pytest.raises(ValueError, match='SUPPLEMENT_UNIQUE_SOURCE_COMPONENTS'):
        f.supplemental_selection('P07', '2021-03-31')
    assert len(removed_guard('supplemental_selection',
        'FUTURE_SUPPLEMENT_UNIQUE_SOURCE_COMPONENTS')('P07', '2021-03-31')[0]) == 2


def test_unregistered_phase_has_no_supplement():
    assert f.supplemental_selection('P00', '2026-07-31') == ([], [])


def test_actual_supplement_composition_requires_explicit_repair_root():
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == 'hydrate')
    start = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                 and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                 and n.value.func.id == 'supplemental_selection')
    nodes = deepcopy(fn.body[start:start+2])
    def run():
        scope = dict(vars(f), arm='P07', cp=dict(source_cursor='2021-03-31', repairs=[]),
                     source_root=None, terms=[], inherited_ordinary=[], ordinary_components=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                     '<actual-data-only-supplement-root-guard>', 'exec'), scope)
        return scope
    with pytest.raises(ValueError, match='SUPPLEMENT_EXPLICIT_REPAIR_ROOT'):
        run()
    assert isinstance(nodes[1], ast.If)
    removed = nodes[1].body.pop(0)
    assert 'FUTURE_SUPPLEMENT_EXPLICIT_REPAIR_ROOT' in ast.unparse(removed)
    assert len(run()['terms']) == 8


@pytest.mark.parametrize('schema,validator_result', [
    ('research.undeclared-input/1', None),
    ('research.leadership-branch-uncertainty-input/1', '0'*64),
])
def test_unselected_or_unvalidated_typed_input_guard_falsifier(tmp_path, monkeypatch, schema, validator_result):
    import system_campaign_financial_branches as branch
    doc = dict(schema=schema, predecessor_checkpoint_sha256='c'*64)
    raw = (json.dumps(doc, sort_keys=True)+'\n').encode(); h = f.sha(raw)
    path = tmp_path/'book/repairs'; path.mkdir(parents=True)
    (path/(h+'.json')).write_bytes(raw)
    cp = dict(repairs=[dict(filename=h+'.json', sha256=h, predecessor_checkpoint_sha256='c'*64)])
    monkeypatch.setattr(branch, 'validate_input', lambda root, parent: validator_result)
    with pytest.raises(ValueError, match='EXACT_RETAINED_TYPED_INPUT'):
        f.remaining_ordinary_terms(cp, [], tmp_path)
    assert removed_guard('remaining_ordinary_terms',
        'FUTURE_INHERITED_ORDINARY_EXACT_RETAINED_TYPED_INPUT')(cp, [], tmp_path) == ([], [])


def test_actual_p07_retained_typed_input_is_independently_validated_without_terminal_reinterpretation():
    import gzip
    root = Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-195/capture-P07-13360217662-001/verified-output')
    if not root.exists():
        pytest.skip('private DATA fixture is local-only')
    root = Path('\\\\?\\'+str(root.resolve()))
    cp = json.loads(gzip.decompress((root/'book/checkpoint.json.gz').read_bytes()))
    terms, _ = f.supplemental_selection('P07', '2021-03-31')
    before = deepcopy((cp, terms))
    remaining, inherited = f.remaining_ordinary_terms(cp, terms, root)
    assert remaining == terms and inherited == [] and (cp, terms) == before
