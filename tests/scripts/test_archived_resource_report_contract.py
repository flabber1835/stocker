"""Archived audit reporters consume private synthetic receipts without authority.

No historical receipt is changed or adopted as current deployment admission.
Git objects are explicit read-only doubles; no Docker, PostgreSQL or broker
process is started by these tests.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))
CLOSEOUT = ROOT/'audit/economic_399/local_closeout/resource_report.py'
PRESSURE = ROOT/'audit/economic_399/postgres_pressure/report.py'


def load(name, source):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


closeout = load('archived_closeout_resource_contract', CLOSEOUT)
pressure = load('archived_postgres_pressure_contract', PRESSURE)
IMAGE = 'sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146'
CONTENT = b'private synthetic immutable object\n'
REVISION = 'f'*40


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


def closeout_fixture(tmp_path, monkeypatch, *, adopted=False, pressure_stage=None):
    evidence, source, output = tmp_path/'campaign', tmp_path/'source', tmp_path/'report.json'
    evidence.mkdir()
    source.mkdir()
    (evidence/'stop').touch()
    objects = {('sentinel/' if i % 3 == 0 else 'shared/' if i % 3 == 1 else 'scripts/')
                +f'private_{i}.py': hashlib.sha256(CONTENT).hexdigest() for i in range(406)}
    objects['docs/private-unbound.txt'] = 'ignored'
    write_json(source/'source-SHA256SUMS.json', objects)
    commands = []
    def git(argv, **kwargs):
        commands.append(argv)
        if argv == ['git', 'rev-parse', 'HEAD']:
            assert kwargs == {'text': True}
            return REVISION+'\n'
        assert argv[:2] == ['git', 'show'] and argv[2].startswith('HEAD:')
        assert argv[2][5:] in objects and kwargs == {}
        return CONTENT
    monkeypatch.setattr(closeout.subprocess, 'check_output', git)
    for stage in (*closeout.STAGES, 'postgres'):
        panel = 'status' in stage or 'http' in stage
        cap = 512*1024**2 if panel else 1024**3 if stage == 'postgres' else 4*1024**3
        cpu = 500_000_000 if panel else 1_500_000_000 if stage == 'postgres' else 2_000_000_000
        inspected = {'State': {'ExitCode': 0, 'OOMKilled': False},
            'HostConfig': {'Memory': cap, 'MemorySwap': cap, 'NanoCpus': cpu,
                'NetworkMode': 'none' if stage == 'postgres' else 'container:private',
                'PortBindings': {}}, 'Image': IMAGE}
        write_json(evidence/f'sentinel-cost-private-{stage}.inspect.json', inspected)
        events = 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0'
        if stage == pressure_stage:
            events = events.replace('max 0', 'max 1')
        metric = {'phase': 'postgres' if stage == 'postgres' else 'stage_complete',
                  'peak': str(cap+3 if stage == pressure_stage else cap-100),
                  'events': events, 'seconds': '0.25'}
        messages = [{'phase': 'ignored_observation'}, metric]
        if 'status' in stage:
            messages += [{'phase': 'complete_status', 'pid': 101},
                         {'phase': 'complete_status', 'pid': 101}]
        elif 'http' in stage:
            messages += [{'phase': 'complete_http', 'shadow': {'status': 'ok'}}]
        elif stage == 'advance':
            messages += [{'scope': 'SYNTHETIC_ACCOUNTING_ONLY',
                          'price_source': 'published_snapshot_bars'}]
        lines = ['unstructured diagnostic retained']+[json.dumps(m) for m in messages]
        if stage in ('publish', 'next_publish'):
            lines += ['SENTINEL_FEED_PROGRESS='+json.dumps(p) for p in (
                {'stage': 'different', 'status': 'completed', 'rows': 2522400},
                {'stage': 'rolling_normalization', 'status': 'started', 'rows': 2522400},
                {'stage': 'rolling_normalization', 'status': 'completed', 'rows': 1},
                {'stage': 'rolling_normalization', 'status': 'completed', 'rows': 2522400})]
        (evidence/(stage+'.log')).write_text('\n'.join(lines)+'\n')
        if adopted:
            (evidence/(stage+'-adopted-container.log')).write_text('\n'.join(lines)+'\n')
    monkeypatch.setattr(sys, 'argv', [str(CLOSEOUT), '--evidence', str(evidence),
                                   '--source', str(source), '--output', str(output)])
    return evidence, source, output, commands


@pytest.mark.parametrize('adopted', [False, True])
@pytest.mark.parametrize('pressure_stage', [None, 'postgres'])
def test_archived_closeout_exact_readonly_receipts_retain_scope_and_limits(tmp_path, monkeypatch, adopted, pressure_stage):
    evidence, source, output, commands = closeout_fixture(tmp_path, monkeypatch,
        adopted=adopted, pressure_stage=pressure_stage)
    before = {str(p):p.read_bytes() for parent in (source,evidence) for p in parent.iterdir() if p.is_file()}
    assert closeout.main() is None
    result = json.loads(output.read_text())
    assert result['scope'] == 'SYNTHETIC_RESOURCE_AND_ACCOUNTING_ONLY'
    assert result['reviewed_commit'] == REVISION and len(result['production_files']) == 406
    assert result['universe'] == 8408 and result['published_rows_per_window'] == 2522400
    assert [r['stage'] for r in result['stages']] == [*closeout.STAGES, 'postgres']
    postgres = result['stages'][-1]
    assert postgres['cap_bytes'] == 1024**3 and postgres['cpu'] == 1.5
    assert postgres['result'] == ('COMPLETED_WITH_PRESSURE' if pressure_stage else 'COMPLETED')
    assert postgres['peak_excess_bytes'] == (3 if pressure_stage else 0)
    assert 'No NAS or provider qualification' in result['limitations']
    assert 'HTTP overall is fail because operational authorities are absent' in result['limitations']
    assert len(commands) == 407
    assert all(Path(path).read_bytes() == value for path,value in before.items())


def test_archived_closeout_cli_executes_same_reporter_without_shell_or_authority(tmp_path, monkeypatch):
    evidence, source, output, commands = closeout_fixture(tmp_path, monkeypatch)
    runpy.run_path(str(CLOSEOUT), run_name='__main__')
    assert json.loads(output.read_text())['reviewed_commit'] == REVISION
    assert len(commands) == 407 and (evidence/'stop').exists()


@pytest.mark.parametrize('case', ['not-finished', 'changed-source', 'missing-source',
    'missing-inspection', 'duplicate-inspection', 'exit', 'oom', 'memory', 'swap',
    'cpus', 'network-app', 'network-pg', 'ports', 'image', 'completion-missing',
    'completion-duplicate', 'metric-oom', 'missing-progress', 'wrong-progress',
    'status-pid', 'http-shadow', 'advance-source', 'adopted-incomplete'])
def test_archived_closeout_missing_or_failed_evidence_cannot_emit_success(tmp_path, monkeypatch, case):
    evidence, source, output, commands = closeout_fixture(tmp_path, monkeypatch)
    if case == 'not-finished':
        (evidence/'stop').unlink()
    elif case in ('changed-source','missing-source'):
        path = source/'source-SHA256SUMS.json'
        hashes = json.loads(path.read_text())
        if case == 'changed-source':
            hashes['sentinel/private_0.py'] = '0'*64
        else:
            hashes.pop('sentinel/private_0.py')
        write_json(path, hashes)
    elif case in ('missing-inspection','duplicate-inspection','exit','oom','memory',
                  'swap','cpus','network-app','network-pg','ports','image'):
        stage = 'postgres' if case == 'network-pg' else 'publish'
        path = evidence/f'sentinel-cost-private-{stage}.inspect.json'
        inspected = json.loads(path.read_text())
        if case == 'missing-inspection':
            path.unlink()
        elif case == 'duplicate-inspection':
            write_json(evidence/'sentinel-cost-other-publish.inspect.json', inspected)
        else:
            if case == 'exit': inspected['State']['ExitCode'] = 1
            elif case == 'oom': inspected['State']['OOMKilled'] = True
            elif case == 'image': inspected['Image'] = 'sha256:'+'0'*64
            else:
                key,value = {'memory':('Memory',1), 'swap':('MemorySwap',1),
                    'cpus':('NanoCpus',1), 'network-app':('NetworkMode','bridge'),
                    'network-pg':('NetworkMode','bridge'), 'ports':('PortBindings',{'5432': []})}[case]
                inspected['HostConfig'][key] = value
            write_json(path, inspected)
    else:
        stage = 'status' if case == 'status-pid' else 'http' if case == 'http-shadow' else 'advance' if case == 'advance-source' else 'publish'
        path = evidence/(stage+'.log')
        lines = path.read_text().splitlines()
        if case == 'completion-missing':
            lines = [l for l in lines if 'stage_complete' not in l]
        elif case == 'completion-duplicate':
            lines += [l for l in lines if 'stage_complete' in l]
        elif case == 'metric-oom':
            lines = [l.replace('oom 0', 'oom 1') for l in lines]
        elif case == 'missing-progress':
            lines = [l for l in lines if not l.startswith('SENTINEL_FEED_PROGRESS=')]
        elif case == 'wrong-progress':
            lines = [l.replace('2522400', '2522399') for l in lines]
        elif case == 'status-pid':
            lines[-1] = lines[-1].replace('101', '102')
        elif case == 'http-shadow':
            lines = [l.replace('"ok"', '"fail"') for l in lines]
        elif case == 'advance-source':
            lines = [l.replace('published_snapshot_bars', 'broker_prices') for l in lines]
        elif case == 'adopted-incomplete':
            path = evidence/'publish-adopted-container.log'
            lines = ['not a completed log']
        path.write_text('\n'.join(lines)+'\n')
    with pytest.raises(AssertionError):
        closeout.main()
    assert not output.exists()


def sample_text(time, phase='baseline', *, peak=200, max_events=0, some=100, full=50):
    return f'''BEGIN {time}
phase {phase}
memory.current
100
memory.peak
{peak}
memory.events
max {max_events}
oom 0
oom_kill 0
oom_group_kill 0
memory.stat
anon 20
shmem 10
file 60
kernel 5
memory.pressure
some avg10=0.00 avg60=0.00 avg300=0.00 total={some}
full avg10=0.00 avg60=0.00 avg300=0.00 total={full}
cpu.stat
usage_usec 500
END
'''


def test_pressure_samples_preserve_cache_non_cache_and_monotone_counters():
    rows = pressure.samples(sample_text(100)+sample_text(102, max_events=2, some=300, full=150))
    assert len(rows) == 2 and rows[0]['file_cache_bytes'] == 50
    assert rows[0]['non_file_cache_estimate_bytes'] == 35
    result = pressure.summarize(rows)
    assert result['sampled_seconds'] == 2 and result['max_sample_gap_seconds'] == 2
    assert result['events_delta']['max'] == 2 and result['total_memory_headroom'] == 'SAMPLED_MARGIN'
    assert result['sampled_non_file_cache_margin_basis_points'] == (pressure.CAP-35)*10000//pressure.CAP
    assert result['some_stall_seconds'] == .0002 and result['some_stall_percent'] == .01
    assert result['full_stall_seconds'] == .0001 and result['full_stall_percent'] == .005
    tight = pressure.samples(sample_text(100, peak=pressure.CAP)+sample_text(102, peak=pressure.CAP))
    assert pressure.summarize(tight)['total_memory_headroom'] == 'TIGHT'


@pytest.mark.parametrize('case', ['empty','truncated','nested','end-without-start',
    'phase-without-start','scalar-without-start','text-without-field','missing-phase',
    'missing-scalar','missing-map','missing-stat','inconsistent-shmem','missing-event',
    'oom','clock','counter-reset'])
def test_pressure_parser_refuses_incomplete_nonmonotone_or_oom_samples(case):
    text = sample_text(100)+sample_text(102)
    if case == 'empty': text = ''
    elif case == 'truncated': text = sample_text(100).removesuffix('END\n')
    elif case == 'nested': text = 'BEGIN 99\n'+text
    elif case == 'end-without-start': text = 'END\n'
    elif case == 'phase-without-start': text = 'phase baseline\n'
    elif case == 'scalar-without-start': text = 'memory.current\n'
    elif case == 'text-without-field': text = 'BEGIN 100\nunknown\n'
    elif case == 'missing-phase': text = text.replace('phase baseline\n', '')
    elif case == 'missing-scalar': text = text.replace('memory.current\n100\n', '')
    elif case == 'missing-map': text = text.replace('cpu.stat\nusage_usec 500\n', '')
    elif case == 'missing-stat': text = text.replace('kernel 5\n', '')
    elif case == 'inconsistent-shmem': text = text.replace('file 60\n', 'file 1\n')
    elif case == 'missing-event': text = text.replace('oom_group_kill 0\n', '')
    elif case == 'oom': text = text.replace('oom 0\n', 'oom 1\n')
    elif case == 'clock': text = sample_text(100)+sample_text(100)
    elif case == 'counter-reset': text = sample_text(100,max_events=1)+sample_text(102,max_events=0)
    with pytest.raises(AssertionError):
        pressure.samples(text)


def test_pressure_summary_refuses_single_sample_and_decreasing_stall_counters():
    rows = pressure.samples(sample_text(100))
    with pytest.raises(AssertionError, match='insufficient samples'):
        pressure.summarize(rows)
    rows = pressure.samples(sample_text(100, some=100)+sample_text(102, some=99))
    with pytest.raises(AssertionError):
        pressure.summarize(rows)


def pressure_fixture(tmp_path, monkeypatch, *, repeated=True):
    evidence = tmp_path/'pressure'
    evidence.mkdir()
    rows = []
    for index, stage in enumerate(pressure.STAGES):
        rows.append(sample_text(100+index*10, stage))
        if repeated:
            rows.append(sample_text(101+index*10, stage, some=200, full=100))
    (evidence/'samples.log').write_text(''.join(rows))
    write_json(evidence/'completed.json', [{'stage':stage} for stage in pressure.STAGES])
    for stage in (*pressure.STAGES, 'postgres'):
        pg = stage == 'postgres'
        write_json(evidence/(stage+'.inspect.json'), [{'Id': 'private-postgres', 'Image': 'private-image',
            'State': {'ExitCode': 0, 'OOMKilled': False},
            'HostConfig': {'Memory':pressure.CAP if pg else 4*pressure.CAP,
                'MemorySwap':pressure.CAP if pg else 4*pressure.CAP,
                'NanoCpus':1_500_000_000 if pg else 2_000_000_000,
                'PortBindings':{}, 'NetworkMode':'none' if pg else 'container:private-postgres'}}])
    monkeypatch.setattr(sys, 'argv', [str(PRESSURE), '--evidence', str(evidence)])
    return evidence


@pytest.mark.parametrize('repeated', [False,True])
def test_archived_pressure_report_keeps_single_and_repeated_phase_limits_explicit(tmp_path, monkeypatch, repeated):
    evidence = pressure_fixture(tmp_path, monkeypatch, repeated=repeated)
    assert pressure.main() is None
    report = json.loads((evidence/'report.json').read_text())
    assert report['scope'] == 'LOCAL_SYNTHETIC_POSTGRESQL_PROFILE'
    assert report['limits'] == {'memory_bytes':pressure.CAP,'swap_total_bytes':pressure.CAP,'cpus':1.5}
    assert set(report['phases']) == set(pressure.STAGES)
    assert all(row['samples'] == (2 if repeated else 1) for row in report['phases'].values())
    assert report['overall']['samples'] == (12 if repeated else 6)
    assert 'No accepted latency budget or NAS qualification.' in report['limitations']
    assert 'Single publisher/reader workload; no concurrent backup qualification.' in report['limitations']


def test_archived_pressure_cli_uses_same_parser_without_live_processes(tmp_path, monkeypatch):
    evidence = pressure_fixture(tmp_path, monkeypatch)
    runpy.run_path(str(PRESSURE), run_name='__main__')
    assert json.loads((evidence/'report.json').read_text())['overall']['samples'] == 12


@pytest.mark.parametrize('case', ['stage-order','pg-network','exit','oom','memory','swap',
                                'cpu','ports','app-network','missing-phase'])
def test_archived_pressure_invalid_container_or_phase_receipts_refuse(tmp_path, monkeypatch, case):
    evidence = pressure_fixture(tmp_path, monkeypatch)
    if case == 'stage-order':
        write_json(evidence/'completed.json', [{'stage':s} for s in reversed(pressure.STAGES)])
    elif case == 'missing-phase':
        text = (evidence/'samples.log').read_text().replace('phase final\n', 'phase missing\n')
        (evidence/'samples.log').write_text(text)
    else:
        path = evidence/('postgres.inspect.json' if case == 'pg-network' else 'publish.inspect.json')
        inspected = json.loads(path.read_text())
        if case == 'exit': inspected[0]['State']['ExitCode'] = 1
        elif case == 'oom': inspected[0]['State']['OOMKilled'] = True
        else:
            key,value = {'pg-network':('NetworkMode','bridge'), 'memory':('Memory',1),
                'swap':('MemorySwap',1), 'cpu':('NanoCpus',1), 'ports':('PortBindings',{'5432':[]}),
                'app-network':('NetworkMode','container:foreign')}[case]
            inspected[0]['HostConfig'][key] = value
        write_json(path, inspected)
    with pytest.raises(AssertionError):
        pressure.main()
    assert not (evidence/'report.json').exists()
