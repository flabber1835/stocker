"""Native source AST, stub gate, and transport checks; no financial execution."""
import ast
from copy import deepcopy
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from full_system_benchmark import save
from system_campaign_parallel_discovery import compile_body
import build_core_variants as source_compiler
import system_campaign_variants as variants
import system_campaign_volatility_native_transport as transport
import system_campaign_volatility_native_gate as gate
import system_campaign_volatility_native_run as run
import system_campaign_volatility_native_parent as parent
import system_campaign_volatility_native_job as job


def private_factory(horizon):
    """Use the original pure source compiler, never import its generated code."""
    tree = ast.parse(Path(source_compiler.__file__).read_bytes())
    owner, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'render']
    material, = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == 'material']
    value = compile_body(material, vars(source_compiler))((HERE.parents[1]/transport.FACTORY).read_text(encoding='utf-8'))
    return variants.replace(value, "value['closes'] = value['closes'][-21:]",
        f"value['closes'] = value['closes'][-{horizon}:]").encode()


@pytest.mark.parametrize('arm,horizon', [('P10',21),('P11',10)])
def test_actual_original_private_factory_bytes_and_horizon_are_bound(arm, horizon):
    spec = parent.specification(arm)
    raw = private_factory(horizon)
    assert hashlib.sha256(raw).hexdigest() == spec['native_signal_factory_sha256']
    value = transport.native_material(raw, expected_sha256=spec['native_signal_factory_sha256'], expected_horizon=horizon)
    assert value['signal_closes'] == horizon and not value['financial_factory_modified']
    with pytest.raises(ValueError, match='FACTORY_AND_FROZEN_PARAMETER'):
        transport.native_material(raw, expected_sha256=spec['native_signal_factory_sha256'], expected_horizon=127)
    with pytest.raises(ValueError, match='EXACT_PRIVATE_SIGNAL_FACTORY'):
        transport.native_material(raw+b'\n', expected_sha256=spec['native_signal_factory_sha256'], expected_horizon=horizon)


@pytest.mark.parametrize('bad', [True, 0, 128, '21', 21.0])
def test_native_expected_horizon_has_exact_integer_type_and_bound(bad):
    raw = private_factory(21)
    with pytest.raises(ValueError, match='FINITE_SIGNAL_HORIZON'):
        transport.native_material(raw, expected_sha256=hashlib.sha256(raw).hexdigest(), expected_horizon=bad)


@pytest.mark.parametrize('slice_text', ['[-21:0]', '[-21::2]', "[-'21':]"])
def test_noncanonical_source_slice_cannot_select_input_history(slice_text):
    raw = private_factory(21).replace(b"value['closes'][-21:]", ("value['closes']"+slice_text).encode())
    with pytest.raises((ValueError, TypeError)):
        transport.native_material(raw, expected_sha256=hashlib.sha256(raw).hexdigest(), expected_horizon=21)


@pytest.mark.parametrize('horizon', [21,10])
def test_native_horizon_flows_through_two_gate_sites_and_one_traversal(monkeypatch, horizon):
    original = gate.original.corrected_tree
    retained = []
    def record(mode):
        value = original(mode)
        retained.append(value)
        return value
    monkeypatch.setattr(gate.original, 'corrected_tree', record)
    gate.compiled_native_gate(horizon)
    calls = [n for n in ast.walk(retained[0]) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'Execution']
    assert len(calls) == 2 and all(ast.unparse(n) == f"Execution('FAST', signal_closes={horizon})" for n in calls)
    monkeypatch.setattr(run, 'profile', lambda: dict(signal_closes=horizon))
    tree = run.diagnostic_tree()
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'Execution']
    assert len(calls) == 1 and ast.unparse(calls[0]) == f"Execution('FAST', signal_closes={horizon})"
    assert 'retained_anchor_qualifications=anchor_gate.commitment()' in ast.unparse(tree)
    assert 'AnchorQualification=AnchorQualification' in ast.unparse(run.worker_tree())


@dataclass(frozen=True)
class Publication:
    session: str
    value: float


def recorder(mutation=None, *, remove_guard=False, interrupt=False):
    fn = gate.native_tree()
    fn.body = [n for n in fn.body if not isinstance(n, ast.ImportFrom)]
    if remove_guard:
        sites = [i for i,n in enumerate(fn.body) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
            and ast.unparse(n.value.func) == 'need' and len(n.value.args) > 1
            and isinstance(n.value.args[1], ast.Constant)
            and n.value.args[1].value == 'V_RETENTION_ALL_ACTUAL_PUBLISHED_AND_RUNTIME_VALUES_EQUAL']
        assert len(sites) == 1
        fn.body.pop(sites[0])
    runtime = SimpleNamespace(advance=lambda result,published: result, checkpoint=lambda result:dict(state_value=result.value))
    modes = []
    def compiled(mode):
        modes.append(mode)
        assert mode == 'FAST', 'COMPLETED_REFERENCE_MUST_NOT_EXECUTE'
        def qualify(root, prior, out, **kwargs):
            for index in range(3):
                result = SimpleNamespace(value=index+(1 if mutation == 'checkpoint' else 0))
                runtime.advance(result, Publication(str(index), 2.0 if mutation == 'publication' else 1.0))
                if interrupt:
                    raise TimeoutError('stub stop after durable native FAST record')
            save(out/'discovery-canonical-qualification.json',dict(status='DIFFERENT' if mutation == 'proof' else 'QUALIFIED'))
        return qualify
    records = [dict(session=str(index),publication_sha256=gate.publication_digest(Publication(str(index),1.0)),
        checkpoint=dict(state_value=index)) for index in range(3)]
    scope = dict(vars(gate.original),runtime=runtime,hosted=lambda:None,compiled_gate=compiled,
        seed_reference=lambda *args:(records,dict(status='QUALIFIED')),progress=gate.progress,phase=gate.phase,
        publication_digest=gate.publication_digest,signal_horizon=21,material_profile=dict(factory_sha256='1'*64))
    return compile_body(fn,scope), modes


def test_only_changed_fast_executes_and_all_successful_records_are_durable(tmp_path):
    call, modes = recorder()
    out = tmp_path/'out'
    call(tmp_path,{},out,selected_file='unused',source_iterator=None,code='STUB')
    assert modes == ['FAST']
    assert len(list((out/'native-fast-progress').glob('*.json.gz'))) == 3
    proof = json.loads((out/'discovery-canonical-qualification.json').read_bytes())
    assert proof['reference_recomputed'] is False and proof['signal_material_closes'] == 21
    assert proof['actual_fast_reference_full_runtime_paths_equal'] and proof['actual_fast_reference_published_sessions_equal']


@pytest.mark.parametrize('mutation', ['checkpoint','publication','proof'])
def test_every_field_of_new_fast_runtime_publication_and_proof_must_match(tmp_path, mutation):
    call, _ = recorder(mutation)
    with pytest.raises(ValueError, match='ALL_ACTUAL'):
        call(tmp_path,{},tmp_path/mutation,selected_file='unused',source_iterator=None,code='STUB')


def test_actual_full_comparison_guard_removal_falsifier(tmp_path):
    call, modes = recorder('checkpoint',remove_guard=True)
    call(tmp_path,{},tmp_path/'removed',selected_file='unused',source_iterator=None,code='STUB')
    assert modes == ['FAST']


def test_interruption_preserves_completed_fast_record_without_combined_pass(tmp_path):
    call, _ = recorder(interrupt=True)
    out = tmp_path/'stopped'
    with pytest.raises(TimeoutError):
        call(tmp_path,{},out,selected_file='unused',source_iterator=None,code='STUB')
    assert json.loads(gzip.decompress((out/'native-fast-progress/0.json.gz').read_bytes()))['session'] == '0'
    assert not (out/'discovery-canonical-qualification.json').exists()


def test_request_retains418_and_has_no_stale_reference_only_or127_configuration():
    value = job.expected_request()
    assert len(value['sources']) == 427 and value['arms'] == ['P10','P11']
    assert value['native_signal_closes'] == {'P10':21,'P11':10}
    assert value['qualify_wait_seconds'] == 1800 and value['discovery_wait_seconds'] == 14400
    assert value['initial_min_disk_bytes'] == 12*1024**3
    assert value['shared_versioned_anchor_proofs_sha256'] == job.ANCHOR_SHA
    assert not {'only_missing_reference_qualification_executed','reused_fast_run_id','signal_material_closes'}.intersection(value)
    assert value['completed_reference_recomputed'] is False
    assert set(json.loads((job.HERE/job.PRIOR).read_bytes())['sources']).issubset(value['sources'])


@pytest.mark.parametrize('arm', ['P10','P11'])
@pytest.mark.parametrize('mode,role', [('qualify','qualify'),('discovery','worker')])
def test_native_entrypoint_and_all_actual_resource_mount_inspection_guards(tmp_path, monkeypatch, arm, mode, role):
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(job.parallel.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.parallel.os,'getgid',lambda:1001,raising=False)
    name = f'capital-system-parallel-discovery-{arm.lower()}-{role}-123-1'
    command = job.worker_command(name,arm,mode,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old')
    assert command[command.index('-B'):] == job.entrypoint(arm,mode)
    assert command[command.index('--network')+1] == 'none'
    assert command[command.index('--memory')+1] == command[command.index('--memory-swap')+1] == '8g'
    assert command[command.index('--cpus')+1] == '2'
    assert sum('target=/previous,readonly' in item for item in command) == (1 if mode == 'qualify' else 0)
    destinations = ['/variant','/frozen','/driver','/out','/old']+(['/previous'] if mode == 'qualify' else [])
    value = dict(Name='/'+name,Image=job.parallel.EXECUTION_IMAGE,Id='1'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(arm,mode),WorkingDir='/variant',User='1001:1001',Env=[],
            Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
        Mounts=[dict(Destination=target,Type='bind',RW=target == '/out') for target in destinations])
    monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(name,'1'*64) == value
    value['Mounts'][-1]['RW'] = True
    with pytest.raises(ValueError,match='MOUNTS'):
        job.inspect(name,'1'*64)


def test_orchestration_adds_admission_before_discard_and_checks_before_traversal():
    tree = job.orchestration_tree()
    text = ast.unparse(tree)
    assert text.index('admit_previous(arm, temp, key)') < text.index("os.environ.pop('GH_TOKEN', None)")
    assert text.index('check_qualification(proof, args.arm)') < text.index("receipt.update(status='DISCOVERY_LAUNCH_ATTEMPTED'")
    assert "need(memory_bytes()['MemAvailable'] >= 10 * 1024 ** 3 and shutil.disk_usage(temp).free >= 10 * 1024 ** 3" in text
    assert 'UNKNOWN_NO_SNAPSHOT' in text and 'known=False' not in text.replace('known = False','')
    assert "note(args.output.parent / 'admission-phase.json', arm" in text


def test_source_admission_and_notes_preserve_every_original_control_flow_guard():
    before = job.risk.adopted('main')
    after = job.orchestration_tree()
    class RemoveAdditions(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value,ast.Call) and ast.unparse(node.value.func) in ('note','admit_previous','check_qualification'):
                return None
            return self.generic_visit(node)
        def visit_ExceptHandler(self, node):
            if node.name == 'native_error':
                node.name = None
            return self.generic_visit(node)
    after = ast.fix_missing_locations(RemoveAdditions().visit(after))
    assert ast.dump(after) == ast.dump(before)


@pytest.mark.parametrize('arm', ['P10','P11'])
def test_atomic_host_note_uses_actual_arm_and_omits_exception_payload(tmp_path, monkeypatch, arm):
    monkeypatch.setenv('GITHUB_RUN_ID','123')
    monkeypatch.setenv('GITHUB_SHA','1'*40)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(job,'memory_bytes',lambda:dict(MemAvailable=12*1024**3))
    path = tmp_path/'note.json'
    job.note(path,arm,'BEFORE_RETAINED_REFERENCE_FETCH')
    job.note(path,arm,'FAILURE',ValueError('PRIVATE_MARKET_OR_FINANCIAL_VALUE'))
    value = json.loads(path.read_bytes())
    assert value['arm'] == arm and value['invariant_code'] is None
    assert value['previous_stage'] == 'BEFORE_RETAINED_REFERENCE_FETCH'
    assert b'PRIVATE_MARKET_OR_FINANCIAL_VALUE' not in path.read_bytes()
    assert not path.with_suffix('.pending').exists()


def test_actual_host_exception_omission_guard_removal_falsifier(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123')
    monkeypatch.setenv('GITHUB_SHA','1'*40)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(job,'memory_bytes',lambda:dict(MemAvailable=12*1024**3))
    fn, = [n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name == 'note']
    field, = [n for n in ast.walk(fn) if isinstance(n,ast.keyword) and n.arg == 'invariant_code']
    assert isinstance(field.value,ast.IfExp)
    field.value = field.value.body
    call = compile_body(fn,vars(job))
    path = tmp_path/'removed.json'
    call(path,'P10','FAILURE',ValueError('PRIVATE_MARKET_OR_FINANCIAL_VALUE'))
    assert b'PRIVATE_MARKET_OR_FINANCIAL_VALUE' in path.read_bytes()


def native_proof(arm):
    spec = parent.specification(arm)
    return dict(qualification_kind='ORIGINAL_RISK_GUARDS_PRESERVED_HELD_MISSING_INPUT_REFUSED',
        held_missing_quote_continuation=False, all_actual_held_quotes_unchanged=True,
        normal_source_packets_unchanged=True, incomplete_toy_position_cash_shares_and_slot_unchanged=True,
        expected_held_input_refusal=dict(status='EXPECTED_ORIGINAL_RISK_INPUT_REFUSAL_QUALIFIED',
            expected_refusal=job.risk.CODES[arm],committed_transitions=0,
            prior_and_publication_unchanged=True,original_hook_restored=True),
        signal_material_closes=spec['native_signal_closes'],
        native_signal_factory_sha256=spec['native_signal_factory_sha256'], reference_recomputed=False,
        actual_fast_reference_full_runtime_paths_equal=True,
        actual_fast_reference_published_sessions_equal=True, financial_source_or_risk_rule_changed=False)


@pytest.mark.parametrize('arm', ['P10','P11'])
def test_qualification_admission_keeps_original_risk_refusal_and_native_equality(arm):
    proof = native_proof(arm)
    job.check_qualification(proof,arm)
    for field,value in [('signal_material_closes',127), ('native_signal_factory_sha256','0'*64),
        ('reference_recomputed',True), ('actual_fast_reference_full_runtime_paths_equal',False),
        ('actual_fast_reference_published_sessions_equal',False), ('financial_source_or_risk_rule_changed',True)]:
        bad = deepcopy(proof)
        bad[field] = value
        with pytest.raises(ValueError,match='ACTUAL_FULL_PUBLISHED_RUNTIME_PROOF'):
            job.check_qualification(bad,arm)
    bad = deepcopy(proof)
    bad['expected_held_input_refusal']['committed_transitions'] = 1
    with pytest.raises(ValueError,match='EXISTING_GUARD_REFUSAL'):
        job.check_qualification(bad,arm)


def test_actual_native_qualification_admission_guard_removal_falsifier():
    fn, = [n for n in ast.parse(Path(job.__file__).read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name == 'check_qualification']
    sites = [i for i,n in enumerate(fn.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
             and ast.unparse(n.value.func) == 'need']
    assert len(sites) == 1
    fn.body.pop(sites[0])
    mutated = compile_body(fn,vars(job))
    bad = native_proof('P10')
    bad['signal_material_closes'] = 127
    mutated(bad,'P10')
