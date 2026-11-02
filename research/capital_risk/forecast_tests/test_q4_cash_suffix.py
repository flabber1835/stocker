"""Metadata, immutable-source and independent cash-review falsifiers only."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import system_campaign_q4_cash_context as context
import system_campaign_q4_cash_facts as facts
import system_campaign_q4_cash_review as review
import system_campaign_p02_q4_cash_job as job

HERE = Path(facts.__file__).parent


def catalog():
    return json.loads((HERE / facts.CATALOG).read_bytes())


def test_exact_31_unconsumed_terms_and_own_admitted_checkpoint():
    value = catalog();before = deepcopy(value)
    assert facts.validate(value) is value and value == before
    assert len({v['security_id'] for v in value['terms']}) == 31
    assert 'CELL' not in {v['ticker'] for v in value['terms']}
    expected = job.expected_request()
    assert expected == json.loads((HERE / 'system-campaign-p02-q4-cash-request.json').read_bytes())
    parent = json.loads((HERE / expected['predecessor_file']).read_bytes())
    assert parent['run_id'] == 41200949097 and parent['selected_session'] == '2023-09-29'
    assert len(parent['repairs']) == 34 and expected['parent_certificate_rows'] == 992
    assert expected['source_archive_limit_bytes'] == 512*1024**2
    assert expected['parent_content_reference_sha256'] == job.digest(job.reference(parent))
    old = job.inherited_request()
    assert len(old['sources']) == 236 and len(expected['sources']) == 247
    assert {n: expected['sources'][n] for n in old['sources']} == old['sources']
    for key in ('qualified_packet_source_sha256', 'canonical_controller_sources', 'ordinary_registry_sha256'):
        assert expected[key] == old[key]


@pytest.mark.parametrize('change', ['price', 'currency', 'consumed', 'count', 'quote', 'cell'])
def test_undeclared_economics_or_consumed_terms_refuse(change):
    value = catalog()
    if change == 'price': value['terms'][0]['added']['cash_per_share'] += 1
    elif change == 'currency': value['terms'][0]['primary_extraction']['currency'] = 'EUR'
    elif change == 'consumed': value['terms'][0]['native_session'] = '2023-09-29'
    elif change == 'count': value['terms'].pop()
    elif change == 'quote': value['same_day_quote_claims'] = ['unproved']
    else: value['excluded_consumed_events'][0]['cross_candidate_equivalence_claimed'] = True
    with pytest.raises(ValueError): facts.validate(value)


def registry_root(tmp_path):
    for name in (context.FILE, 'system-campaign-wwe-registry-extension.json', context.registry.REGISTRY):
        (tmp_path / name).write_bytes((HERE / name).read_bytes())
    return tmp_path


def test_registry_preserves_every_original_and_wwe_group(tmp_path):
    root = registry_root(tmp_path);obj = context.CashRegistry(root)
    old = obj.wwe.registrations(root)
    assert obj.registrations(root) == [*old, catalog()['commitment_group']]
    assert obj.wwe.registrations(root) == old


@pytest.mark.parametrize('change', ['parent', 'stem', 'traversal'])
def test_registry_rebinding_and_unsafe_paths_refuse(tmp_path, change):
    root = registry_root(tmp_path)
    value = json.loads((root / context.FILE).read_bytes())
    if change == 'parent': value['required_wwe_extension_sha256'] = '0'*64
    elif change == 'stem': value['groups'][0]['reference_stem'] = 'research:old/'
    else: value['groups'][0]['private_file'] = '../escape.json'
    (root / context.FILE).write_text(json.dumps(value), encoding='utf8')
    with pytest.raises(ValueError): context.CashRegistry(root)


def test_cash_preflight_alias_is_restored_on_failure(monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core, 'hosted', lambda: None)
    obj = object.__new__(context.CashPreflight)
    original = context.cash.analyze_new_catalog
    with pytest.raises(RuntimeError):
        with obj:
            assert context.cash.analyze_new_catalog == obj.analyze
            raise RuntimeError('injected exception')
    assert context.cash.analyze_new_catalog is original


def tap_fixture():
    value = dict(frozen_year_member_checks=[dict(member='observations-2023.csv.gz', all_rows_read=2)],
                 terms=[dict(added=dict(session='2023-10-06'), security_id='HZNP')])
    tap = facts.RecognitionTap(value)
    raw = [dict(session='2023-10-04', security_id='OTHER'), dict(session='2023-10-05', security_id='HZNP')]
    tap.original = lambda archive, member: iter(raw)
    tap.inputs = SimpleNamespace(_archive_rows=tap.original)
    return tap, raw


def test_complete_source_tap_returns_same_row_objects_and_requires_restoration():
    tap, rows = tap_fixture()
    actual = list(tap.rows(None, 'observations-2023.csv.gz'))
    assert all(a is b for a, b in zip(actual, rows))
    assert tap.proof()['original_reader_restored'] is True
    tap.inputs._archive_rows = tap.rows
    with pytest.raises(ValueError): tap.proof()


@pytest.mark.parametrize('change', ['recognition_quote', 'short_scan', 'unconsumed_generator', 'other_year'])
def test_quote_tap_rejects_incomplete_scans_or_conflicts(change):
    tap, rows = tap_fixture()
    if change == 'recognition_quote': rows[-1]['session'] = '2023-10-06'
    elif change == 'short_scan': rows.pop()
    member = 'other.csv.gz' if change == 'other_year' else 'observations-2023.csv.gz'
    with pytest.raises(ValueError):
        stream = tap.rows(None, member)
        next(stream) if change == 'unconsumed_generator' else list(stream)
        tap.proof()


def cash_fixture(monkeypatch):
    # Only independent arithmetic over inert JSON snapshots, never Core replay.
    monkeypatch.setattr(review, 'hosted', lambda: None)
    monkeypatch.setattr(review, 'save', lambda *args: None)
    ep = dict(security_id='HZNP', current_shares=3)
    empty = dict(episodes={}, unresolved_terminals={}, terminal_pending_sessions={})
    parent = dict(source_cursor='2023-10-05', run=dict(state=dict(wealth_core=dict(episodes={'0': ep}))))
    event = dict(event_type='CASH_MERGER', session='2023-10-06', security_id='HZNP',
        price=116.5, cash_delta=349.5, shares_delta=-3, detail=dict(shares=3, reference='primary'))
    cp = dict(sha256='1'*64, source_cursor='2023-10-06', run=dict(state=dict(ledger=dict(events=[event]))))
    cat = dict(terms=[dict(ticker='HZNP', security_id='HZNP', added=dict(
        session='2023-10-06', cash_per_share=116.5, reference='primary'))])
    row = dict(session='2023-10-06', evidence=dict(research_entry_audit=dict(
        opening_accounting=dict(wealth_core=deepcopy(empty)), closing_accounting=dict(wealth_core=deepcopy(empty)))))
    monkeypatch.setattr(review, 'committed_rows', lambda *args: [row])
    return cp, parent, cat, row


def test_independent_actual_cash_entitlement_and_unheld_event(tmp_path, monkeypatch):
    cp, parent, cat, _ = cash_fixture(monkeypatch)
    result = review.actual_cash(tmp_path, cp, parent, cat, tmp_path / 'review.json')
    assert result['actual_checks']['HZNP']['actual_cash'] == 349.5
    parent['run']['state']['wealth_core']['episodes'] = {}
    cp['run']['state']['ledger']['events'] = []
    assert review.actual_cash(tmp_path, cp, parent, cat, tmp_path / 'review.json')['actual_checks']['HZNP']['actual_cash'] == 0


@pytest.mark.parametrize('change', ['double', 'cash', 'price', 'quantity', 'clock', 'reference', 'pending', 'position'])
def test_independent_cash_reviewer_rejects_economic_mutations(tmp_path, monkeypatch, change):
    cp, parent, cat, row = cash_fixture(monkeypatch)
    event = cp['run']['state']['ledger']['events'][0]
    if change == 'double': cp['run']['state']['ledger']['events'].append(deepcopy(event))
    elif change == 'cash': event['cash_delta'] += .01
    elif change == 'price': event['price'] += .01
    elif change == 'quantity': event['detail']['shares'] = 2
    elif change == 'clock': event['session'] = '2023-10-05'
    elif change == 'reference': event['detail']['reference'] = 'other'
    elif change == 'pending': row['evidence']['research_entry_audit']['closing_accounting']['wealth_core']['terminal_pending_sessions']['HZNP'] = 1
    else: row['evidence']['research_entry_audit']['opening_accounting']['wealth_core']['episodes']['0'] = dict(security_id='HZNP', current_shares=3)
    with pytest.raises(ValueError): review.actual_cash(tmp_path, cp, parent, cat, tmp_path / 'review.json')


def test_actual_entitlement_guard_removal_falsifier(tmp_path, monkeypatch):
    cp, parent, cat, _ = cash_fixture(monkeypatch)
    cp['run']['state']['ledger']['events'][0]['cash_delta'] += 1
    with pytest.raises(ValueError): review.actual_cash(tmp_path, cp, parent, cat, tmp_path / 'review.json')
    fn, = [n for n in ast.parse(Path(review.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'actual_cash']
    for node in ast.walk(fn):
        if isinstance(node, ast.For):
            node.body[:] = [n for n in node.body if not (isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call) and any(isinstance(a, ast.Constant)
                and a.value == 'Q4_ACTUAL_LEDGER_ENTITLEMENT_DATE_PRICE_QUANTITY_EXACTLY_ONCE' for a in n.value.args))]
    scope = dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-independent-cash-entitlement-guard-removed>', 'exec'), scope)
    assert scope['actual_cash'](tmp_path, cp, parent, cat, tmp_path / 'review.json')['actual_checks']['HZNP']['actual_cash'] == 350.5


def test_metadata_request_and_single_writer_entrypoints_are_exact(monkeypatch):
    correct = dict(Config=dict(Cmd=['-B', '-u', '/driver/system_campaign_p02_q4_cash_run.py',
        '--mode', 'economic', '--spec', '/out/spec.json', '--request', '/driver/system-campaign-p02-q4-cash-request.json']))
    monkeypatch.setattr(job, 'prior_inspect', lambda *args: correct)
    assert job.inspect('capital-system-factual-p02-worker-1-1') == correct
    correct['Config']['Cmd'][2] = '/driver/system_campaign_p02_wwe_run.py'
    with pytest.raises(ValueError): job.inspect('capital-system-factual-p02-worker-1-1')
    run = ast.parse((HERE / 'system_campaign_p02_q4_cash_run.py').read_bytes())
    calls = [v for v in ast.walk(run) if isinstance(v, ast.Call)]
    gate, = [v for v in calls if ast.unparse(v.func) == 'timing.call' and v.args
             and isinstance(v.args[0], ast.Constant) and v.args[0].value == 'actual_packets_and_own_cash_gate']
    finance, = [v for v in calls if ast.unparse(v.func) == 'timing.call' and v.args
               and isinstance(v.args[0], ast.Constant) and v.args[0].value == 'financial_driver_total']
    assert gate.lineno < finance.lineno
    assert 'system_campaign_normal_reference import admit' in Path(job.__file__).read_text()
