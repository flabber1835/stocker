"""Public backed build/prepare preserve the selected baseline's actual mode."""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_local_delivery_cli import (
    inputs, OLD, NEW, OLD_IMAGE, NEW_IMAGE, images, qualification,
)
from tests.scripts.test_sentinel_backed_local_patch import patch, backed_host
from tests.scripts.test_sentinel_clean_retired_delivery import retired_host
from tests.scripts.test_sentinel_backed_predecessor import complete


@pytest.fixture
def route(inputs, monkeypatch):
    def setup(mode='POST_TRADE', fault=None):
        root = inputs.folder.parent
        actual = retired_host() if mode == 'POST_TRADE' else backed_host()
        state = deepcopy(actual.state)
        pg = dict(command=['postgres', '-c', 'archive_mode=on', '-c', 'archive_command=/canonical/archive %p %f'],
            container='postgres-container', image='postgres-image', source='/docker/volume',
            started='2026-01-01T00:00:00Z', volume='sentinel_sentinel_pgdata')
        groups = ('alerts', 'delivered_alerts', 'events', 'fanouts', 'recipients', 'delivered_recipients')
        history = {key: {} for key in groups}; history['events'] = {'old': {'immutable': True}}
        native = {'asset': '7'}
        anchor_commit, anchor_image = 'f'*40, 'sha256:'+'e'*64
        anchor_root = root/'anchor'; (anchor_root/'.git').mkdir(parents=True)
        anchor = anchor_root/'artifacts/sentinel/authority/deployments/initial/activation-receipt.json'
        anchor.parent.mkdir(parents=True)
        anchor.write_text(json.dumps(dict(schema='sentinel.activation-receipt/1', operational_ready=True,
            activation_mode='dual', completed_at='2026-01-01T00:00:00Z', git_commit=anchor_commit,
            runtime_image=anchor_image, control_generation=99, certificate_sha256='certificate')))
        previous_source = root/'previous-source'; (previous_source/'.git').mkdir(parents=True)
        previous = root/'previous'; previous.mkdir()
        predecessor = dict(commit=anchor_commit, image=anchor_image, postgres=pg, system=state['system'])
        identity = {'source': '1'*64, 'shadow_config': '3'*64, 'wealth': '4'*64}
        candidate = dict(commit=OLD, image=OLD_IMAGE, source_identity=identity)
        report = previous/'qualification.json'
        report.write_text(json.dumps(dict(commit=OLD, final=True, source_files_unchanged=True,
            source_files={'sentinel/module.py': 'a'*64})))
        qualified = dict(report_path=str(report), report_sha256=patch.sha256_file(report),
            commit=OLD, passed=True, source_files={'sentinel/module.py': 'a'*64})
        request = dict(schema='sentinel.local-paper-delivery/3', operation_id='prior-started',
            handoff_mode=mode, source=str(previous_source), deployment=str(anchor_root),
            predecessor=predecessor, candidate=candidate, qualification=qualified,
            allowed_delta=['sentinel/module.py'], created_at='2026-01-01T00:00:00Z')
        built = dict(schema=patch.builder.BUILD_SCHEMA, **candidate, source=str(previous_source),
            deployment=str(anchor_root), foundation=predecessor,
            predecessor_receipt=dict(path=str(anchor), sha256=patch.sha256_file(anchor)),
            qualification={key: qualified[key] for key in ('report_path', 'report_sha256')})
        proof = {'canonical': 'unchanged'}
        receipt = complete(dict(operation=previous, request=request, built=built, pg=pg),
            final_stage='APPLICATIONS_STARTED', artifacts=dict(preserved=deepcopy(state),
                native_positions=native, notification_history=history,
                canonical_proof=proof, successor_proof_sha256=patch.digest(proof)))

        # Git, SQL, Docker and native GETs are the external edges. All public
        # command, journal, baseline, financial and prepare guards stay real.
        inputs.files['scripts/sentinel_env.py'] = '# fixture literal reader\n'
        (inputs.source/'scripts/sentinel_env.py').write_text(inputs.files['scripts/sentinel_env.py'])
        inputs.report['source_files'] = qualification.source_files(inputs.source)
        inputs.report_path.write_text(json.dumps(inputs.report))
        inputs.report_sha = qualification.sha256_file(inputs.report_path)
        for name in importlib.import_module(patch.builder.__package__+'.host').COMPOSE:
            (inputs.deployment/name).write_bytes((inputs.source/name).read_bytes())
        real_qualification = importlib.import_module(patch.builder.__package__+'.qualification')
        monkeypatch.setattr(real_qualification, 'git', inputs.git)
        monkeypatch.setattr(patch.builder, 'git', inputs.git)
        old, new = images()
        anchor_metadata = dict(Id=anchor_image, Config={'Labels': {'org.opencontainers.image.revision': anchor_commit}})
        audit = dict(sql=[], native=0, notifications=0, applications=0, builds=0, requests=[])
        parent_host = patch.BackedHost

        class Host(parent_host):
            def __init__(self, request, folder, **kwargs):
                audit['requests'].append(deepcopy(request))
                super().__init__(request, folder, **kwargs)

            def load_values(self):
                return dict(ALPACA_BASE_URL='https://paper-api.alpaca.markets',
                    SENTINEL_LOCAL_PAPER_ACCOUNT_ID='PAPER-Z', SENTINEL_LOCAL_PAPER_BACKUP_POLICY='REQUIRED_V1',
                    SENTINEL_GIT_COMMIT=OLD, SENTINEL_RUNTIME_IMAGE_DIGEST=OLD_IMAGE)

            def image_metadata(self, reference, **kwargs):
                if reference == anchor_image: return deepcopy(anchor_metadata)
                return deepcopy(old if reference in {OLD_IMAGE, 'sentinel-local-paper:'+OLD[:8]} else new)

            def git(self, *args): return inputs.git(self.source, *args)
            def git_bytes(self, *args): return inputs.files[args[1].split(':', 1)[1]].encode()

            def sql(self, statement):
                if statement == patch.checks.NOTIFICATION_SQL:
                    audit['notifications'] += 1
                    current = deepcopy(history)
                    if fault == 'history': current['events']['old'] = {'immutable': False}
                    return current
                if statement in {patch.checks.snapshot_sql(key) for key in ('PRE_OPEN', 'POST_TRADE')}:
                    audit['sql'].append(statement)
                    if statement != patch.checks.snapshot_sql(mode): return json.loads('')
                    current = deepcopy(state)
                    if fault == 'financial': current['commands_md5'] = 'changed'
                    return current
                assert statement.startswith("SELECT json_build_object('system'")
                return dict(system=state['system'], generation=99, certificate='certificate')

            def container(self, service):
                assert service == 'sentinel-postgres'
                return dict(Id=pg['container'], Image=pg['image'], State={'Running': True, 'StartedAt': pg['started']},
                    Mounts=[dict(Destination='/var/lib/postgresql/data', Type='volume', Name=pg['volume'],
                        Source='changed' if fault == 'postgres' else pg['source'])], Config={'Cmd': pg['command']})

            def containers(self, services):
                audit['applications'] += 1
                return {key: dict(Image=OLD_IMAGE, State=dict(Running=True,
                    Health={'Status': 'unhealthy' if fault == 'application' else 'healthy'},
                    OOMKilled=False, Restarting=False)) for key in services}

            def compose(self, values, *args, **kwargs):
                if patch.checks.NATIVE_POSITIONS in args:
                    audit['native'] += 1
                    return SimpleNamespace(stdout=json.dumps({'asset': '8'} if fault == 'native' else native))
                assert args == ('config', '--format', 'json')
                return SimpleNamespace(stdout=json.dumps({'services': {
                    'sentinel-postgres': {'command': pg['command']}, 'sentinel-shadow': {'environment': dict(
                        SENTINEL_SHADOW_OBSERVATION_ID='fixture', SENTINEL_SHADOW_STARTING_CASH='50000',
                        SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY='fixture')}}}))

            def run(self, command, **kwargs):
                assert command[:2] == ['docker', 'run'] and '--network' in command
                if 'production_strategy()[1]' in command[-1]:
                    return SimpleNamespace(stdout=json.dumps({'strategy': 'e'*64}))
                commit = next(value.split('=', 1)[1] for value in command if value.startswith('SENTINEL_GIT_COMMIT='))
                return SimpleNamespace(stdout=json.dumps(dict(identity, source=('1' if commit == OLD else '2')*64)))

            @contextmanager
            def owned(self): yield

        monkeypatch.setattr(patch, 'BackedHost', Host)
        def docker_build(command, **kwargs):
            assert command[:2] == ['docker', 'build'] and '--network' in command
            audit['builds'] += 1; kwargs['stdout'].write(b'Completed source-only Docker build\n')
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(patch.builder.subprocess, 'run', docker_build)
        return SimpleNamespace(inputs=inputs, receipt=receipt, audit=audit, mode=mode,
            original_receipt=receipt.read_bytes())
    return setup


def build(case, *, explicit=True):
    value = case.inputs
    args = ['build', '--source', str(value.source), '--deployment', str(value.deployment),
        '--predecessor-receipt', str(case.receipt), '--qualification', str(value.report_path),
        '--qualification-sha256', value.report_sha, '--allowed-delta', str(value.delta),
        '--allowed-delta-sha256', qualification.sha256_file(value.delta), '--operation-dir', str(value.folder),
        '--commit', NEW, '--allow-started-predecessor']
    if explicit: args += ['--handoff-mode', case.mode]
    return patch.main(args)


def prepare(case, *, explicit=True):
    artifact = case.inputs.folder/'build.json'
    target = case.inputs.folder.parent/'fresh-operation'
    args = ['prepare', '--operation-dir', str(target), '--build-record', str(artifact),
        '--build-sha256', qualification.sha256_file(artifact), '--operation-id', 'fresh-operation']
    if explicit: args += ['--handoff-mode', case.mode]
    return patch.main(args), target


@pytest.mark.parametrize('mode,explicit', [('POST_TRADE', True), ('PRE_OPEN', False)])
def test_public_build_and_prepare_use_actual_selected_started_baseline(route, mode, explicit):
    case = route(mode)
    assert build(case, explicit=explicit) == 0
    result, folder = prepare(case, explicit=explicit)
    assert result == 0
    assert case.audit['builds'] == 1 and case.audit['native'] == case.audit['notifications'] == 2
    assert case.audit['applications'] == 2
    assert case.audit['sql'] == [patch.checks.snapshot_sql(mode)]*2
    request = patch.Journal(folder).request
    assert request['handoff_mode'] == mode and request['candidate']['commit'] == NEW
    assert patch.builder.operation_build(folder)['predecessor_receipt']['allow_started'] is True
    assert patch.Journal(folder).read()['stage'] == 'NEW'
    assert case.receipt.read_bytes() == case.original_receipt


@pytest.mark.parametrize('fault', ['financial', 'native', 'history', 'postgres', 'application'])
def test_public_forward_build_preserves_all_started_predecessor_guards(route, fault):
    case = route(fault=fault)
    assert build(case) == 2
    assert case.audit['builds'] == 0
    assert not (case.inputs.folder/'build-started.json').exists()
    assert case.receipt.read_bytes() == case.original_receipt


@pytest.mark.parametrize('command', ['build', 'prepare'])
def test_mode_drop_has_an_executed_public_path_falsifier(route, monkeypatch, command):
    case = route()
    if command == 'prepare': assert build(case) == 0
    source = inspect.getsource(patch.main)
    needle = ('deployment=args.deployment,handoff_mode=args.handoff_mode' if command == 'build' else
        "candidate=dict(commit=built['commit']),handoff_mode=args.handoff_mode")
    assert source.count(needle) == 1
    namespace = dict(vars(patch)); exec(source.replace(needle, needle.rsplit(',handoff_mode=', 1)[0]), namespace)
    monkeypatch.setattr(patch, 'main', namespace['main'])
    assert (build(case) if command == 'build' else prepare(case)[0]) == 2
    assert case.audit['sql'][-1] == patch.checks.snapshot_sql('PRE_OPEN')
    assert case.audit['builds'] == (1 if command == 'prepare' else 0)
    assert case.receipt.read_bytes() == case.original_receipt
