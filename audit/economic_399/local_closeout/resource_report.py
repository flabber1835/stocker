"""Summarize a completed capped synthetic campaign; missing evidence fails."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


STAGES = ('publish', 'initialize', 'status', 'http', 'next_publish', 'advance',
          'advanced_status', 'advanced_http')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert (args.evidence / 'stop').exists(), 'campaign has not finished'
    sources = json.loads((args.source / 'source-SHA256SUMS.json').read_text())
    bound = {}
    for name, expected in sources.items():
        if name.startswith(('sentinel/', 'shared/', 'scripts/')):
            blob = subprocess.check_output(['git', 'show', 'HEAD:' + name])
            actual = hashlib.sha256(blob).hexdigest()
            assert actual == expected, ('production changed since campaign', name)
            bound[name] = actual
    assert len(bound) == 406, len(bound)
    rows = []
    for stage in (*STAGES, 'postgres'):
        paths = list(args.evidence.glob('sentinel-cost-*-'+stage+'.inspect.json'))
        assert len(paths) == 1, (stage, paths)
        inspected = json.loads(paths[0].read_text())
        state, host = inspected['State'], inspected['HostConfig']
        assert state['ExitCode'] == 0 and not state['OOMKilled'], (stage, state)
        panel = 'status' in stage or 'http' in stage
        cap = 512*1024**2 if panel else 1024**3 if stage == 'postgres' else 4*1024**3
        cpus = 500000000 if panel else 1500000000 if stage == 'postgres' else 2000000000
        assert host['Memory'] == host['MemorySwap'] == cap, stage
        assert host['NanoCpus'] == cpus, stage
        if stage == 'postgres':
            assert host['NetworkMode'] == 'none', stage
        else:
            assert host['NetworkMode'].startswith('container:'), stage
        assert not host['PortBindings'], stage
        assert inspected['Image'] == 'sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146'
        messages, progress = [], []
        log = args.evidence / (stage+'-adopted-container.log')
        if not log.exists():
            log = args.evidence / (stage+'.log')
        for line in log.read_text().splitlines():
            if line.startswith('{'):
                messages.append(json.loads(line))
            elif line.startswith('SENTINEL_FEED_PROGRESS='):
                progress.append(json.loads(line.split('=', 1)[1]))
        if stage in ('publish', 'next_publish'):
            assert any(p.get('stage') == 'rolling_normalization'
                       and p.get('status') == 'completed' and p.get('rows') == 2522400
                       for p in progress), 'missing 8,408 x 300 normalized input rows'
        phase = 'postgres' if stage == 'postgres' else 'stage_complete'
        completed = [m for m in messages if m.get('phase') == phase]
        assert len(completed) == 1, (stage, 'completion record missing')
        metric = completed[0]
        events = dict(line.split() for line in metric['events'].splitlines())
        assert all(int(events[key]) == 0 for key in ('oom', 'oom_kill', 'oom_group_kill')), (stage, events)
        # memory.max enforcement can reclaim and briefly overshoot without OOM
        # (kernel cgroup-v2 contract). Retain pressure as an unqualified margin,
        # never turn it into a claim of headroom or acceptable latency.
        pressure = (any(int(events[key]) for key in ('low', 'high', 'max'))
                    or int(metric['peak']) >= cap)
        detail = [m for m in messages if m.get('phase') in ('complete_status', 'complete_http')
                  or m.get('scope') == 'SYNTHETIC_ACCOUNTING_ONLY']
        if 'status' in stage:
            assert len(detail) == 2 and detail[0]['pid'] == detail[1]['pid'], stage
        if 'http' in stage:
            assert len(detail) == 1 and detail[0]['shadow']['status'] == 'ok', stage
        if stage == 'advance':
            assert len(detail) == 1 and detail[0]['price_source'] == 'published_snapshot_bars'
        rows.append(dict(stage=stage, cap_bytes=cap, cpu=cpus/1e9,
                         result='COMPLETED_WITH_PRESSURE' if pressure else 'COMPLETED',
                         peak_excess_bytes=max(0, int(metric['peak']) - cap),
                         metric=metric, details=detail))
    report = dict(scope='SYNTHETIC_RESOURCE_AND_ACCOUNTING_ONLY',
                  reviewed_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  universe=8408, published_rows_per_window=2522400,
                  production_files=bound, stages=rows,
                  limitations=['No accepted real-history publication replay',
                               'No accepted latency budget', 'No NAS or provider qualification',
                               'PostgreSQL headroom is unqualified when reclaim/limit pressure is reported',
                               'HTTP overall is fail because operational authorities are absent',
                               'Two repeated status reads do not prove unlimited process lifetime'])
    args.output.write_bytes((json.dumps(report, indent=2)+'\n').encode())
    for row in rows:
        print(row['stage'], row['metric'].get('seconds'), row['metric']['peak'], 'bytes;', row['result'])


if __name__ == '__main__':
    main()
