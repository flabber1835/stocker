"""Review I/O repair controls; no canonical financial imports or replay."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

class Fence:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('REVIEW_SCRATCH_DATA_ONLY:' + fullname)

sys.meta_path.insert(0, Fence())
import system_campaign_financial_additional_sensor_review as repair


def actual_phase():
    source = Path(repair.original.__file__).parent / 'system-campaign-qualified-own-uncertainty-input-facts.json'
    return json.loads(source.read_bytes())['phases']['532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd']


def fixture(tmp_path):
    root, target = tmp_path / 'old', tmp_path / 'scratch'
    root.mkdir(); target.mkdir()
    event = b'synthetic original private event'
    (root / 'hydrated-uncertainty-event.json').write_bytes(event)
    descriptors = []
    for i in range(20):
        doc = dict(synthetic_input=i)
        if i == 19:
            doc = dict(schema='research.leadership-branch-uncertainty-input/1', source_evidence=[dict(
                reference='research:system-optimization-002/leadership-uncertainty/private-event/1',
                sha256=repair.data.sha(event))])
        raw = json.dumps(doc).encode()
        pin = repair.data.sha(raw)
        name = 'book/repairs/' + pin + '.json'
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        descriptors.append(dict(filename=pin + '.json', sha256=pin))
    observers = [dict(material_file=f'material-{i}.json', effective_file=f'effective-{i}.json', projection=None)
                 for i in range(3)]
    resources = ['provider-source/SHARADAR_ACTIONS.zip', 'provider-alias-proof.json']
    resources += [v[k] for v in observers for k in ('material_file', 'effective_file')]
    pins = {}
    for name in resources:
        raw = ('synthetic:' + name).encode(); path = root / name
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw); pins[name] = repair.data.sha(raw)
    cp = dict(sha256='a' * 64, repairs=deepcopy(descriptors))
    phase = dict(origin_outer_sha256=cp['sha256'], original_descriptors=descriptors,
                 origin_root_admission_sha256='b' * 64, inherited_ordinary_observers=observers,
                 original_branch_descriptor=deepcopy(descriptors[-1]))
    origin = dict(ordinary_origin_outer_sha256=cp['sha256'], origin_root_admission_sha256='b' * 64, input_files=pins)
    (root / repair.data.ORIGIN).write_bytes(repair.data.encoded(origin))
    return root, target, cp, phase


def test_all_exact_inputs_and_resources_copied_without_financial_state(tmp_path):
    args = fixture(tmp_path)
    expected = repair.stage_inputs(*args)
    assert len(expected) == 29
    root, target, cp, phase = args
    for name in expected: assert (target / name).read_bytes() == (root / name).read_bytes()
    assert not (target / 'book/checkpoint.json.gz').exists()
    assert not (target / 'book/daily.jsonl').exists()


@pytest.mark.parametrize('change', ['missing_input', 'tampered_input', 'foreign_origin', 'missing_resource',
    'tampered_resource', 'bad_descriptor_name', 'unsafe_resource', 'foreign_descriptors'])
def test_missing_or_foreign_input_generation_refuses(tmp_path, change):
    root, target, cp, phase = fixture(tmp_path)
    path = root / 'book/repairs' / cp['repairs'][0]['filename']
    if change == 'missing_input': path.unlink()
    elif change == 'tampered_input': path.write_bytes(b'changed')
    elif change == 'foreign_origin': cp['sha256'] = 'c' * 64
    elif change == 'missing_resource': (root / 'material-0.json').unlink()
    elif change == 'tampered_resource': (root / 'material-0.json').write_bytes(b'changed')
    elif change == 'bad_descriptor_name': cp['repairs'][0]['filename'] = '../escape.json'; phase['original_descriptors'] = deepcopy(cp['repairs'])
    elif change == 'unsafe_resource': phase['inherited_ordinary_observers'][0]['material_file'] = '../escape.json'
    else: cp['repairs'].pop(0)
    with pytest.raises((ValueError, FileNotFoundError)): repair.stage_inputs(root, target, cp, phase)


def test_existing_scratch_input_must_be_byte_identical(tmp_path):
    root, target, cp, phase = fixture(tmp_path)
    path = target / 'book/repairs' / cp['repairs'][0]['filename'];path.parent.mkdir(parents=True)
    path.write_bytes(b'foreign')
    with pytest.raises(ValueError, match='IDENTICAL_COLLIDING'): repair.stage_inputs(root, target, cp, phase)


@pytest.mark.parametrize('change', ['missing_event', 'tampered_event', 'tampered_branch', 'foreign_branch',
                                  'wrong_schema', 'missing_reference', 'duplicate_reference', 'bad_hash'])
def test_original_branch_event_dependency_refuses_missing_or_foreign_binding(tmp_path, change):
    root, target, cp, phase = fixture(tmp_path)
    event = root / 'hydrated-uncertainty-event.json'
    branch = root / 'book/repairs' / phase['original_branch_descriptor']['filename']
    if change == 'missing_event': event.unlink()
    elif change == 'tampered_event': event.write_bytes(b'changed')
    elif change == 'tampered_branch': branch.write_bytes(b'changed')
    elif change == 'foreign_branch': phase['original_branch_descriptor'] = dict(filename='0' * 64 + '.json', sha256='0' * 64)
    else:
        doc = json.loads(branch.read_bytes())
        if change == 'wrong_schema': doc['schema'] = 'terminal-repair/1'
        elif change == 'missing_reference': doc['source_evidence'] = []
        elif change == 'duplicate_reference': doc['source_evidence'] *= 2
        else: doc['source_evidence'][0]['sha256'] = '../foreign'
        raw = repair.data.encoded(doc); pin = repair.data.sha(raw)
        descriptor = dict(filename=pin + '.json', sha256=pin)
        (branch.parent / descriptor['filename']).write_bytes(raw)
        cp['repairs'][-1] = deepcopy(descriptor)
        phase['original_descriptors'] = deepcopy(cp['repairs'])
        phase['original_branch_descriptor'] = descriptor
    with pytest.raises((ValueError, FileNotFoundError)):
        repair.stage_inputs(root, target, cp, phase)


def test_event_byte_guard_removal_accepts_corrupted_private_witness(tmp_path):
    args = fixture(tmp_path)
    (args[0] / 'hydrated-uncertainty-event.json').write_bytes(b'changed event')
    with pytest.raises(ValueError, match='EXACT_INPUT_RESOURCE_BYTES'): repair.stage_inputs(*args)
    fn = repair.data.function(Path(repair.__file__).read_bytes(), 'stage_inputs')
    class Remove(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and any(isinstance(v, ast.Constant)
                and v.value == 'REVIEW_SCRATCH_EXACT_INPUT_RESOURCE_BYTES' for v in node.value.args):
                return None
            return self.generic_visit(node)
    fn = Remove().visit(fn); scope = dict(vars(repair))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-event-byte-guard>', 'exec'), scope)
    assert scope['stage_inputs'](*args)['hydrated-uncertainty-event.json']


def test_single_insert_undo_restores_entire_frozen_reconstruction_AST():
    phase = actual_phase()
    fn = repair.reconstruction_tree(phase)
    inserted, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and ast.unparse(n.value) == 'stage_inputs(root, target, cp0, p)']
    fn.body.remove(inserted)
    original = repair.data.function(Path(repair.original.__file__).read_bytes(), 'ordinary_reconstruction')
    assert ast.dump(fn, include_attributes=False) == ast.dump(original, include_attributes=False)


def test_wrong_frozen_runtime_generation_refuses():
    phase = deepcopy(actual_phase())
    phase['policy_source_files'][Path(repair.original.__file__).name] = '0' * 64
    with pytest.raises(ValueError, match='UNCHANGED_FROZEN'): repair.reconstruction_tree(phase)


@pytest.mark.parametrize('label', ['REVIEW_SCRATCH_EXACT_INPUT_RESOURCE_BYTES', 'REVIEW_SCRATCH_EXACT_TWENTY_ORIGIN_DESCRIPTORS'])
def test_guard_removal_really_accepts_wrong_input_generation(tmp_path, label):
    args = fixture(tmp_path)
    root, target, cp, phase = args
    if label.endswith('RESOURCE_BYTES'):
        (root / 'book/repairs' / cp['repairs'][0]['filename']).write_bytes(b'changed')
    else: cp['repairs'].pop(0)
    with pytest.raises(ValueError, match=label): repair.stage_inputs(*args)
    fn = repair.data.function(Path(repair.__file__).read_bytes(), 'stage_inputs')
    class Remove(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and any(isinstance(v, ast.Constant) and v.value == label for v in node.value.args):
                return None
            return self.generic_visit(node)
    fn = Remove().visit(fn); scope = dict(vars(repair))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-scratch-input-guard>', 'exec'), scope)
    assert scope['stage_inputs'](*args)


@pytest.mark.parametrize('prefix', ['research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas'])
def test_import_fence(prefix):
    with pytest.raises(ImportError): Fence().find_spec(prefix)
