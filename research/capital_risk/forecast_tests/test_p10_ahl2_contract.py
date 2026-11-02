"""Pure metadata/stub/source AST checks; canonical execution is hosted only."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import system_campaign_p10_ahl2_contract as contract
import system_campaign_p10_ahl2_input as input4
import system_campaign_p10_ahl2_epoch as epoch
import system_campaign_p10_ahl2_parent as parent
import system_campaign_p10_ahl2_replay as replay
from system_campaign_p10_ahl2_observe import cash_postcondition
from system_campaign_p10_ahl2_gate import qualification_valid, STATUS


@pytest.fixture
def spec():
    return contract.specification()


def test_exact_own_source_metadata_and_future_input(spec):
    assert spec['source_map']['physical'] == 516 and spec['source_map']['canonical'] == 224
    assert spec['base']['policy'] == contract.POLICY and len(spec['old_descriptors']) == 3
    value = input4.expected_document(spec)
    assert value['predecessor_checkpoint_sha256'] == spec['runtime_checkpoint_sha256']
    assert len(value['add']) == len(value['suppress']) == 1
    assert value['add'][0]['session'] == '2019-02-15' and value['add'][0]['cash_per_share'] == 42.75
    assert value['suppress'][0]['session'] == '2019-02-14'
    assert input4.validate_document(value, spec) == value


@pytest.mark.parametrize('change', [
    lambda x:x.update(predecessor_checkpoint_sha256='0'*64),
    lambda x:x['add'][0].update(cash_per_share=42.76),
    lambda x:x['add'][0].pop('delivered_security_id'),
    lambda x:x['add'][0].update(session='2019-02-14'),
    lambda x:x['suppress'][0].update(term_sha256='0'*64),
    lambda x:x['add'].append(deepcopy(x['add'][0])),
    lambda x:x.update(unselected_arm='P02')])
def test_only_exact_complete_own_fourth_document(spec, change):
    value = input4.expected_document(spec)
    change(value)
    with pytest.raises(ValueError, match='P10_ONLY_EXACT_OWN_FOURTH_ORDINARY_DOCUMENT'):
        input4.validate_document(value, spec)


def test_input_exact_predicate_removal_falsifier(spec):
    raw = (HERE / 'system_campaign_p10_ahl2_input.py').read_bytes()
    fn = contract.function(raw, 'validate_document')
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Compare(self, node):
            if ast.unparse(node) == 'value == expected_document(spec)':
                self.count += 1
                return ast.copy_location(ast.Constant(True), node)
            return self.generic_visit(node)
    remove = Remove()
    mutant = remove.visit(fn)
    assert remove.count == 1
    value = input4.expected_document(spec)
    value['add'][0]['cash_per_share'] = 99.
    with pytest.raises(ValueError):
        input4.validate_document(value, spec)
    scope = dict(vars(input4))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[mutant], type_ignores=[])), '<removed-scope-guard>', 'exec'), scope)
    assert scope['validate_document'](value, spec) == value


def test_canonical_loader_called_with_exact_own_predecessor(tmp_path, spec):
    path = tmp_path / 'input.json'
    raw = input4.document_bytes(spec)
    path.write_bytes(raw)
    from types import SimpleNamespace
    calls = []
    def loader(p, **kw):
        calls.append((p, kw))
        return SimpleNamespace(sha256=contract.sha(raw), earliest_affected_session='2019-02-14',
            model_dump=lambda **_:input4.expected_document(spec))
    obj = input4.load(path, spec, loader)
    assert calls == [(path, dict(resume_session='2019-02-01', predecessor_checkpoint_sha256=spec['runtime_checkpoint_sha256']))]
    assert input4.descriptor(obj, spec)['sha256'] == contract.sha(raw)
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='P10_EXACT_RAW_FOURTH_INPUT_BYTES'):
        input4.load(path, spec, loader)
    assert len(calls) == 1


def packet(spec, day):
    terms = [deepcopy(spec['native_term']['added'])] if day == '2019-02-15' else []
    return dict(day=day, bars=[dict(security_id='OTHER', raw_close=7.)], terminal=terms,
                spins=[], dividends=[], metadata={'same':True})


def test_packet_sparse_addition_preserves_every_other_field(spec):
    a, b = packet(spec, '2019-02-15'), packet(spec, '2019-02-15')
    a['terminal'] = []
    assert input4.packet_change(a, b, spec=spec, material=deepcopy)['all_nonterminal_fields_exact']
    b['bars'][0]['raw_close'] = 8.
    with pytest.raises(ValueError, match='ALL_QUOTES_BARS_DIVIDENDS_SPINS_AND_SOURCE_FIELDS_UNCHANGED'):
        input4.packet_change(a, b, spec=spec, material=deepcopy)


def test_no_fake_current_source_bar(spec):
    a, b = packet(spec, '2019-02-15'), packet(spec, '2019-02-15')
    a['terminal'] = []
    for p in (a, b): p['bars'].append(dict(security_id=contract.SID, raw_close=42.75))
    with pytest.raises(ValueError, match='P10_NO_FEB15_AHL2_SOURCE_BAR_OR_PRICE_INVENTED'):
        input4.packet_change(a, b, spec=spec, material=deepcopy)


def zero_pair(spec):
    value = deepcopy(spec)
    state = dict(last_processed_session='2019-02-01', wealth_core={'preserved':'entire'})
    value['state_sha256'] = contract.digest(state)
    before = dict(schema='stub', state=state, state_sha256=contract.digest(state), policy=contract.POLICY,
                  input_sha256=spec['input_sha256'], identity={'same':True})
    before['checkpoint_sha256'] = contract.digest(before)
    value['runtime_checkpoint_sha256'] = before['checkpoint_sha256']
    descriptors = value['old_descriptors'] + [dict(filename='fourth.json', sha256='f'*64)]
    after = deepcopy(before)
    after['input_sha256'] = contract.digest(dict(base=value['base'], repairs=descriptors))
    after['checkpoint_sha256'] = contract.digest({k:v for k,v in after.items() if k != 'checkpoint_sha256'})
    return value, before, after, descriptors


def test_zero_changes_only_input_and_runtime_identity(spec):
    value, before, after, descriptors = zero_pair(spec)
    epoch.zero_invariants(before, after, spec=value, old_descriptors=value['old_descriptors'], descriptors=descriptors,
        input_hash=lambda base, repairs:contract.digest(dict(base=base, repairs=repairs)))


@pytest.mark.parametrize('field', ['state', 'policy', 'input_sha256', 'identity'])
def test_zero_rejects_other_changes(spec, field):
    value, before, after, descriptors = zero_pair(spec)
    after[field] = {'changed':True} if field in ('state','identity') else 'changed'
    with pytest.raises(ValueError):
        epoch.zero_invariants(before, after, spec=value, old_descriptors=value['old_descriptors'], descriptors=descriptors,
            input_hash=lambda base, repairs:contract.digest(dict(base=base, repairs=repairs)))


def inspection(spec, role):
    entry = next(v for v in spec['inspections'].values() if v['role'] == role)
    mode = 'qualify' if role == 'qualify' else 'discovery'
    mounts = ['/variant','/frozen','/driver','/out','/old'] + (['/previous'] if role == 'qualify' else [])
    value = dict(Name=entry['name'], Id=entry['id'], Image='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d',
        State=dict(Running=False, OOMKilled=False, ExitCode=entry['exit_code']),
        HostConfig=dict(NetworkMode='none', Memory=8*1024**3, MemorySwap=8*1024**3, NanoCpus=2000000000,
            ReadonlyRootfs=True, PidsLimit=64, CapDrop=['ALL'], SecurityOpt=['no-new-privileges']),
        Config=dict(WorkingDir='/variant', User='1001:1001', Env=[],
            Cmd=['-B','-u','/driver/system_campaign_volatility_native_run.py','--mode',mode,'--arm','P10','--spec','/out/spec.json']),
        Mounts=[dict(Type='bind', Destination=n, RW=n=='/out') for n in mounts])
    return value, entry


@pytest.mark.parametrize('role', ['worker','qualify'])
def test_old_native_entrypoint_and_mount_fences(spec, role):
    value, entry = inspection(spec, role)
    parent.stopped(value, entry, spec)
    value['Config']['Cmd'][2] = '/driver/system_campaign_discovery_suffix_run.py'
    with pytest.raises(ValueError, match='DIAGNOSTIC_EXACT_KNOWN_ENTRYPOINT'):
        parent.stopped(value, entry, spec)


@pytest.mark.parametrize('change', [lambda x:x['State'].update(Running=True),
    lambda x:x['HostConfig'].update(MemorySwap=16*1024**3),
    lambda x:x['Config'].update(User='0:0'),
    lambda x:x['Mounts'][0].update(RW=True),
    lambda x:x['Config']['Env'].append('GH_TOKEN=bad')])
def test_old_actual_stop_refuses_wrong_fences(spec, change):
    value, entry = inspection(spec, 'worker')
    change(value)
    with pytest.raises(ValueError): parent.stopped(value, entry, spec)


def test_source_bound_iterator_and_only_native_transport_ast():
    iterator = replay.iterator_tree()
    assert ast.unparse(iterator).count('input_path(descriptor)') == 1
    fast, reference = replay.replay_tree('FAST'), replay.replay_tree('REFERENCE')
    for tree in (iterator, fast, reference): compile(tree, '<AST-only>', 'exec')
    ft, rt = ast.unparse(fast), ast.unparse(reference)
    assert "Execution('FAST', signal_closes=21)" in ft
    assert ft.replace("Execution('FAST', signal_closes=21)", "Execution('REFERENCE', signal_closes=21)") == rt
    assert 'bind_checkpoint(value, binding)' in ft and 'advance_recorded(run, published)' in ft


def test_parent_admission_preserves_actual_authenticate_before_plaintext():
    tree = parent.admission_tree()
    compile(ast.Module(body=[tree], type_ignores=[]), '<admission-AST-only>', 'exec')
    text = ast.unparse(tree)
    assert text.index('authenticate(z, asset, key)') < text.index('tarfile.open')
    assert 'validate_contents(dest, spec, inventory)' in text and 'return dest' in text
    assert 'P10_ORIGINAL_KNOWN_FAILURE_NOT_RELABELLED' in text


def test_q_gate_cannot_be_summary_only_wrong_count_or_endpoint(spec):
    summary = dict(schema='research.p10-ahl2-changed-qualification/1', status=STATUS,
        financial_authority=False, qualifier_state_adopted=False, original_diagnostic_file_sha256=spec['diagnostic_checkpoint_sha256'],
        candidate_transitions=10, qualified_through='2019-02-15', first_session='2019-02-04',
        full_FAST_REFERENCE_publication_runtime_event_proof_equal=True, actual_old_refusal_reproduced=True, all21_guard_preserved=True,
        actual_new_canonical_roundtrips=[dict(mode=m,session=d,checkpoint_sha256='c'*64,state_sha256='d'*64,full_state_equal=True)
            for m in ('FAST','REFERENCE') for d in ('2019-02-04','2019-02-05','2019-02-06','2019-02-07','2019-02-08',
                '2019-02-11','2019-02-12','2019-02-13','2019-02-14','2019-02-15')])
    qualification_valid(summary, spec)
    for key, bad in [('candidate_transitions',True),('candidate_transitions',9),('qualified_through','2019-02-14'),
                     ('actual_old_refusal_reproduced',False),('qualifier_state_adopted',True)]:
        value = dict(summary, **{key:bad})
        with pytest.raises(ValueError): qualification_valid(value, spec)


def test_cash_ledger_operation_order_and_wrong_nominal_refuse():
    sid = contract.SID
    before = dict(cash=9000., episodes={'0':dict(security_id=sid,current_shares=7)}, slots={'0':{'occupied_by':sid}})
    after = dict(cash=9299.25, episodes={}, slots={'0':{'occupied_by':None}})
    event = dict(event_type='CASH_MERGER', security_id=sid, price=42.75, cash_delta=299.25,
        shares_delta=-7, fees=0.0, cash_before=9000., cash_after=9299.25,
        detail=dict(shares=7,reference='retained-primary'))
    result = cash_postcondition(before, after, {'events':[]}, {'events':[event]},
        dict(cash_per_share=42.75,reference='retained-primary'), {'applied':True})
    assert result['actual_quantities'] == [7] and result['nominal_cash'] == 299.25
    event['cash_delta'] = 299.26
    with pytest.raises(ValueError, match='P10_EACH_ACTUAL_EXACT_CONTRACTUAL_CASH_LEDGER_POST'):
        cash_postcondition(before, after, {'events':[]}, {'events':[event]},
            dict(cash_per_share=42.75,reference='retained-primary'), {'applied':True})


def test_no_top_level_canonical_imports_in_new_runtime_modules():
    for path in HERE.glob('system_campaign_p10_ahl2_*.py'):
        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('sentinel','stock_strategy_shared','research.pooled_'))
