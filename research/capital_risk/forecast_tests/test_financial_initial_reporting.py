"""Fresh archive/reporting authority falsifiers; no canonical financial runtime."""
import ast
from copy import deepcopy
import io
import json
from pathlib import Path
import zipfile

import pytest

import system_campaign_financial_partial as p
import system_campaign_financial_resume as m


def target():
    return json.loads((p.HERE / m.PARTIALS).read_bytes())['arms']['P00']


def test_one_fresh_target_has_no_continuation_or_performance_authority(monkeypatch):
    monkeypatch.setattr(m,'SELECTED_ARMS',('P00',))
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')
    spec = target(); seed = p.initial_reporting_seed(spec)
    assert seed['measured_closes'] == 0 and seed['selected_session'] == '2017-06-30'
    assert spec['measured_closes'] == 169 and spec['selected_session'] == '2018-08-31'
    assert p.reporting_seed(spec) == seed
    assert 'P00' not in p.ADMISSIONS
    assert spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
    request = m.expected_request()
    assert request['admitted_checkpoints'] == {} and request['initial_reporting_origins'] == {'P00': seed}
    assert request['maximum_parallel_financial_workers'] == 0


@pytest.mark.parametrize('change', ['artifact', 'origin', 'tail', 'arm', 'authority', 'seed', 'old_request'])
def test_other_origin_or_checkpoint_cannot_replace_fresh_target(change):
    spec = target()
    if change == 'artifact': spec['artifact_id'] += 1
    elif change == 'origin': spec['fresh_origin_admission']['previous_book_selected'] = True
    elif change == 'tail': spec['measured_closes'] += 1
    elif change == 'arm': spec['arm'] = 'P01'
    elif change == 'authority': spec['financial_authority'] = True
    elif change == 'seed': spec['initial_monthly_seed']['outer_sha256'] = '0' * 64
    else: spec['fresh_request_member']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='EXACT_FRESH_INITIAL_REPORTING_TARGET'):
        p.initial_reporting_seed(spec)


def test_initial_target_digest_guard_removal_falsifier():
    spec = target(); spec['initial_monthly_seed']['outer_sha256'] = '0' * 64
    with pytest.raises(ValueError): p.initial_reporting_seed(spec)
    fn = next(n for n in ast.parse(Path(p.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == 'initial_reporting_seed')
    fn.body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call))]
    ns = dict(vars(p)); exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                                  '<removed-initial-target-guard>', 'exec'), ns)
    assert ns['initial_reporting_seed'](spec)['outer_sha256'] == '0' * 64


@pytest.mark.parametrize('mode', ['OWN_ADMITTED_FINANCIAL_CONTINUATION', 'READONLY_FROZEN_SOURCE_WITNESSES'])
def test_p00_initial_review_cannot_request_finance_or_source_capture(monkeypatch, mode):
    monkeypatch.setattr(m, 'EXECUTION_MODE', mode)
    monkeypatch.setattr(m, 'SELECTED_ARMS', ('P00',))
    with pytest.raises((ValueError, KeyError)): m.expected_request()


def fresh_archive(monkeypatch, *, change=None):
    spec = target()
    fresh = json.loads((p.HERE / p.FRESH_REQUEST).read_bytes())
    receipt = dict(status=spec['receipt_status'], performance_admitted=False,
                   candidate_id=fresh['candidate_id'], **spec['prior_stops'])
    staging = dict(status='STAGING_PASSED', run_id=str(spec['run_id']), source_commit=spec['head'],
        protocol_sha256=p.PROTOCOL, runtime_image=p.IMAGE, execution_image=p.EXECUTION_IMAGE,
        source_files_verified=514, members_verified=591, manifest_sha256=fresh['frozen_input_manifest_sha256'],
        authenticated_before_parsing=True, offline_image_source_verified=True,
        runtime_index_config_layer_chain_verified=True, replay_started=False)
    values = {spec['receipt_name']: receipt, 'full-core-staging.json': staging,
        'ephemeral-runner-capacity.json': {'synthetic_capacity': True},
        'fresh-origin-admission-P00.json': deepcopy(spec['fresh_origin_admission']),
        'fresh-origin-export-qualification-P00.json': dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED',
            arm='P00', financial_sessions_advanced=0, credentials_saved=False)}
    if change == 'inherited': values['fresh-origin-admission-P00.json']['previous_book_selected'] = True
    elif change == 'candidate': receipt['candidate_id'] = 'other'
    elif change == 'protocol': staging['protocol_sha256'] = spec['protocol_sha256']
    elif change == 'stop': receipt['worker']['stopped'] = False
    elif change == 'marker': values['fresh-origin-export-qualification-P00.json']['financial_sessions_advanced'] = 1
    elif change == 'stage': staging['replay_started'] = True
    blobs = {n: json.dumps(v, sort_keys=True).encode() for n, v in values.items()}
    spec['public_members'] = {n: dict(bytes=len(b), sha256=p.sha(b)) for n, b in blobs.items()}
    monkeypatch.setattr(p, 'FRESH_TARGET_SHA', p.digest(spec))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for n, b in blobs.items():
            if change != 'missing' or n != 'fresh-origin-admission-P00.json': z.writestr(n, b)
        z.writestr(spec['encrypted_output']['name'], b'synthetic ciphertext; not parsed')
        if change == 'extra': z.writestr('extra', b'x')
    out.seek(0)
    return spec, zipfile.ZipFile(out)


def test_fresh_archive_preserves_distinct_stage_and_search_protocols(monkeypatch):
    spec, archive = fresh_archive(monkeypatch)
    assert p.PROTOCOL != spec['protocol_sha256']
    assert p.public_names(spec, archive) == set(archive.namelist())
    assert p.review_name(spec) == 'core-review.json'


@pytest.mark.parametrize('change', ['inherited', 'candidate', 'protocol', 'stop', 'marker', 'stage', 'missing', 'extra'])
def test_fresh_archive_authority_and_inventory_falsifiers(monkeypatch, change):
    spec, archive = fresh_archive(monkeypatch, change=change)
    with pytest.raises(ValueError): p.public_names(spec, archive)


def stats_fixture():
    spec = target(); seed = p.initial_reporting_seed(spec)
    required = ['pooled', 'owned55_previous', 'compact_previous', 'spy']
    parent = dict(completed=0, stats=None, journals=seed['journals'])
    current = dict(base=spec['base'], stats=dict(primary='pooled', required_series=required,
                   series={n: dict(initial_nav='50000') for n in required}))
    class RecordedStats:
        @staticmethod
        def fresh(*args, **kwargs): return args, kwargs
        @staticmethod
        def from_dict(raw): return ('retained', raw)
    return spec, parent, current, RecordedStats


def test_null_own_zero_measurement_seed_uses_exact_fresh_reporting_arguments():
    spec, parent, current, cls = stats_fixture(); before = deepcopy((parent, current))
    args, kwargs = p.reporting_stats(cls, parent, current, spec)
    assert args == ('2018-01-02', {n: '50000' for n in current['stats']['required_series']})
    assert kwargs == dict(primary='pooled', required_series=tuple(current['stats']['required_series']))
    assert (parent, current) == before
    parent['stats'] = dict(retained='already admitted')
    assert p.reporting_stats(cls, parent, current, spec) == ('retained', parent['stats'])


@pytest.mark.parametrize('change', ['count', 'daily', 'monthly', 'capital', 'start', 'primary', 'required', 'baseline', 'series'])
def test_null_seed_never_resets_existing_reporting(change):
    spec, parent, current, cls = stats_fixture()
    if change == 'count': parent['completed'] = 1
    elif change in ('daily', 'monthly'): parent['journals'][change]['bytes'] = 1
    elif change == 'capital': current['base']['capital'] = '50001'
    elif change == 'start': current['base']['start'] = '2018-01-03'
    elif change == 'primary': current['stats']['primary'] = 'spy'
    elif change == 'required': current['stats']['required_series'].pop()
    elif change == 'baseline': current['stats']['series']['pooled']['initial_nav'] = '49999'
    else: current['stats']['series']['other'] = dict(initial_nav='50000')
    with pytest.raises(ValueError): p.reporting_stats(cls, parent, current, spec)


def test_zero_measurement_guard_removal_falsifier():
    spec, parent, current, cls = stats_fixture(); parent['completed'] = 1
    with pytest.raises(ValueError): p.reporting_stats(cls, parent, current, spec)
    fn = next(n for n in ast.parse(Path(p.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == 'reporting_stats')
    guard = next(n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and any(isinstance(a, ast.Constant) and a.value == 'PARTIAL_ONLY_EXACT_ZERO_MEASUREMENT_REPORTING_BOOTSTRAP'
                         for a in n.value.args))
    fn.body.remove(guard); ns = dict(vars(p))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<removed-zero-measurement-guard>', 'exec'), ns)
    assert ns['reporting_stats'](cls, parent, current, spec)[0][0] == '2018-01-02'


def archived_worker(phase='economic'):
    spec = target()
    expected = next(v for v in spec['inspections'].values() if v['phase'] == phase)
    destinations = ['/variant', '/frozen', '/driver', '/out'] + (['/evidence'] if phase == 'review' else [])
    command = ['-B', '-u', '/driver/system_campaign_candidate.py', '--mode', phase]
    if phase == 'review': command += ['--evidence-root', '/evidence']
    value = dict(Name=expected['name'], Id=expected['id'], Image=p.EXECUTION_IMAGE,
        HostConfig=dict(NetworkMode='none', Memory=8 * 1024**3, MemorySwap=8 * 1024**3,
            NanoCpus=2000000000, PidsLimit=64, ReadonlyRootfs=True, CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges']),
        Mounts=[dict(Type='bind', Destination=n, RW=n == '/out') for n in destinations],
        Config=dict(WorkingDir='/variant', User=expected['user'], Env=[],
            Labels={'research.study': 'full-system-search-20261029',
                    'research.role': 'review' if phase == 'review' else 'worker'},
            Entrypoint=['python'], Cmd=command))
    return spec, expected, value


@pytest.mark.parametrize('phase', ['economic', 'review'])
def test_original_candidate_inspector_uses_archived_state_without_docker(phase):
    spec, expected, value = archived_worker(phase); before = deepcopy(value)
    assert p.archived_inspection(spec, expected, value, None) == before
    assert value == before


@pytest.mark.parametrize('change', ['network', 'entrypoint', 'command', 'uid', 'old_mount', 'credential', 'mutable'])
def test_original_candidate_inspection_fences_refuse(change):
    spec, expected, value = archived_worker()
    if change == 'network': value['HostConfig']['NetworkMode'] = 'host'
    elif change == 'entrypoint': value['Config']['Entrypoint'] = ['sh']
    elif change == 'command': value['Config']['Cmd'] += ['--resume', '/old/book']
    elif change == 'uid': value['Config']['User'] = '0:0'
    elif change == 'old_mount': value['Mounts'].append(dict(Type='bind', Destination='/old', RW=False))
    elif change == 'credential': value['Config']['Env'] = ['GH_TOKEN=synthetic']
    else: value['Mounts'][0]['RW'] = True
    with pytest.raises(ValueError): p.archived_inspection(spec, expected, value, None)


def test_candidate_entrypoint_guard_removal_falsifier():
    spec, expected, value = archived_worker(); value['Config']['Cmd'] += ['--resume', '/old/book']
    with pytest.raises(ValueError): p.archived_inspection(spec, expected, value, None)
    fn = next(n for n in ast.parse(Path(p.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == 'archived_inspection')
    guard = next(n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and any(isinstance(a, ast.Constant) and a.value == 'PARTIAL_EXACT_ORIGINAL_CANDIDATE_ENTRYPOINT'
                         for a in n.value.args))
    fn.body.remove(guard); ns = dict(vars(p))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<removed-candidate-entrypoint-guard>', 'exec'), ns)
    assert ns['archived_inspection'](spec, expected, value, None) == value


def test_fresh_reader_changes_only_original_inventory_site_and_review_location():
    original = next(n for n in ast.parse(Path(p.crypto.__file__).read_bytes()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'admit')
    adapted = p.admission_tree(p.review_name(target()))
    class UndoInventory(ast.NodeTransformer):
        sites = 0
        def visit_Call(self, node):
            if ast.unparse(node) == 'public_names(spec, z)':
                self.sites += 1
                return ast.parse("{spec['receipt_name'], 'full-core-staging.json', asset['name']}", mode='eval').body
            return self.generic_visit(node)
    undo = UndoInventory(); restored = undo.visit(adapted)
    assert undo.sites == 1
    assert ast.dump(restored, include_attributes=False) == ast.dump(original, include_attributes=False)
