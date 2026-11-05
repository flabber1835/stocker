"""Exact original review with authenticated scratch input reconstruction only."""
import ast
import json
from pathlib import Path, PurePosixPath
from types import FunctionType

import system_campaign_financial_additional_sensor as data
import system_campaign_financial_additional_sensor_runtime as original


def stage_inputs(root, target, cp0, phase):
    root, target = Path(root), Path(target)
    data.need(cp0['sha256'] == phase['origin_outer_sha256']
              and cp0['repairs'] == phase['original_descriptors'] and len(cp0['repairs']) == 20,
              'REVIEW_SCRATCH_EXACT_TWENTY_ORIGIN_DESCRIPTORS')
    value = original.origin(root)
    data.need(value['ordinary_origin_outer_sha256'] == cp0['sha256']
              and value['origin_root_admission_sha256'] == phase['origin_root_admission_sha256'],
              'REVIEW_SCRATCH_ORIGINAL_INPUT_GENERATION')
    expected = {}
    for d in cp0['repairs']:
        data.need(d['filename'] == d['sha256'] + '.json' and Path(d['filename']).name == d['filename'],
                  'REVIEW_SCRATCH_SAFE_DESCRIPTOR_NAME')
        expected['book/repairs/' + d['filename']] = d['sha256']
    branch = phase['original_branch_descriptor']
    data.need(branch in cp0['repairs'], 'REVIEW_SCRATCH_EXACT_ORIGINAL_BRANCH_DESCRIPTOR')
    raw = (root / 'book/repairs' / branch['filename']).read_bytes()
    data.need(data.sha(raw) == branch['sha256'], 'REVIEW_SCRATCH_EXACT_BRANCH_DESCRIPTOR_BYTES')
    document = json.loads(raw)
    reference = 'research:system-optimization-002/leadership-uncertainty/private-event/1'
    witnesses = [e['sha256'] for e in document['source_evidence'] if e['reference'] == reference]
    data.need(document['schema'] == 'research.leadership-branch-uncertainty-input/1'
              and len(witnesses) == 1 and len(witnesses[0]) == 64
              and all(c in '0123456789abcdef' for c in witnesses[0]),
              'REVIEW_SCRATCH_UNIQUE_ORIGINAL_BRANCH_PRIVATE_EVENT_BINDING')
    expected['hydrated-uncertainty-event.json'] = witnesses[0]
    resources = {'provider-source/SHARADAR_ACTIONS.zip', 'provider-alias-proof.json'}
    for record in phase['inherited_ordinary_observers']:
        resources.update((record['material_file'], record['effective_file']))
        if record['projection'] is not None:
            resources.add(record['projection']['payload_file'])
    for name in resources:
        data.need(name in value['input_files'], 'REVIEW_SCRATCH_RESOURCE_IN_AUTHENTICATED_ORIGIN')
        data.need(name not in expected or expected[name] == value['input_files'][name],
                  'REVIEW_SCRATCH_DESCRIPTOR_RESOURCE_GENERATIONS_AGREE')
        expected[name] = value['input_files'][name]
    for name, pin in expected.items():
        relative = PurePosixPath(name)
        data.need(not relative.is_absolute() and '..' not in relative.parts and ':' not in name and '\\' not in name,
                  'REVIEW_SCRATCH_SAFE_RESOURCE_PATH')
        raw = (root / name).read_bytes()
        data.need(data.sha(raw) == pin, 'REVIEW_SCRATCH_EXACT_INPUT_RESOURCE_BYTES')
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            data.need(destination.read_bytes() == raw, 'REVIEW_SCRATCH_IDENTICAL_COLLIDING_INPUT_RESOURCE')
        else:
            with destination.open('xb') as stream:
                stream.write(raw)
    return {name:pin for name,pin in sorted(expected.items())}


def reconstruction_tree(phase):
    raw = Path(original.__file__).read_bytes()
    data.need(data.sha(raw) == phase['policy_source_files'][Path(original.__file__).name],
              'REVIEW_SCRATCH_UNCHANGED_FROZEN_ADDITIONAL_RUNTIME')
    fn = data.function(raw, 'ordinary_reconstruction')
    site, = [i for i,n in enumerate(fn.body) if isinstance(n, ast.Expr)
             and ast.unparse(n.value) == 'target.mkdir()']
    fn.body.insert(site + 1, ast.parse('stage_inputs(root, target, cp0, p)').body[0])
    return ast.fix_missing_locations(fn)


def reconstruction(phase):
    fn = reconstruction_tree(phase)
    namespace = dict(vars(original), stage_inputs=stage_inputs)
    exec(compile(ast.Module(body=[fn], type_ignores=[]),
                 '<original-ordinary-reconstruction-with-authenticated-scratch-inputs>', 'exec'), namespace)
    return namespace['ordinary_reconstruction']


def review(parent, evidence, out, spec, old):
    original.hosted()
    phase = data.phase(spec)
    data.need(phase is not None, 'REVIEW_SCRATCH_ONLY_EXPLICIT_ADDITIONAL_PHASE')
    adapted = reconstruction(phase)
    function = original.review
    data.need(function.__closure__ is None, 'REVIEW_SCRATCH_NO_HIDDEN_REVIEW_CLOSURE')
    reviewed = FunctionType(function.__code__, dict(function.__globals__, ordinary_reconstruction=adapted),
                            function.__name__, function.__defaults__)
    reviewed.__kwdefaults__ = function.__kwdefaults__
    data.need(reviewed.__code__ is function.__code__, 'REVIEW_SCRATCH_ORIGINAL_WHOLE_REVIEW_CODE')
    return reviewed(parent, evidence, out, spec, old)
