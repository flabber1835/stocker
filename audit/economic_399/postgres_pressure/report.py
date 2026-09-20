"""Retain cache and non-cache observations separately; never confer NAS authority."""
import argparse
import json
from pathlib import Path


CAP = 1024**3
STAGES = ('baseline', 'publish', 'scan1', 'scan2', 'storage', 'final')
SCALARS = ('memory.current', 'memory.peak')
MAPS = ('memory.events', 'memory.stat', 'memory.pressure', 'cpu.stat')


def samples(text):
    result = []
    current = None
    field = None
    for line in text.splitlines():
        if line.startswith('BEGIN '):
            assert current is None, 'incomplete sample'
            current = {'time': float(line.split()[1])}
            field = None
        elif line == 'END':
            assert current is not None
            assert all(k in current for k in ('phase', *SCALARS, *MAPS)), current
            stat = current['memory.stat']
            assert all(k in stat for k in ('anon', 'shmem', 'file', 'kernel')), stat
            assert stat['file'] >= stat['shmem'], stat
            current['file_cache_bytes'] = stat['file'] - stat['shmem']
            current['non_file_cache_estimate_bytes'] = stat['anon'] + stat['shmem'] + stat['kernel']
            events = current['memory.events']
            assert all(k in events for k in ('max', 'oom', 'oom_kill', 'oom_group_kill'))
            assert all(events[k] == 0 for k in ('oom', 'oom_kill', 'oom_group_kill')), events
            if result:
                assert current['time'] > result[-1]['time'], 'clock did not advance'
                for key in ('max', 'oom', 'oom_kill', 'oom_group_kill'):
                    assert events[key] >= result[-1]['memory.events'][key], 'counter reset'
            result.append(current)
            current = None
        elif line.startswith('phase '):
            assert current is not None
            current['phase'] = line.split()[1]
        elif line in (*SCALARS, *MAPS):
            assert current is not None
            field = line
            if line in MAPS:
                current[field] = {}
        else:
            assert current is not None and field is not None, line
            if field in SCALARS:
                current[field] = int(line)
            elif field == 'memory.pressure':
                key, *values = line.split()
                current[field][key] = dict(pair.split('=') for pair in values)
            else:
                key, value = line.split()
                current[field][key] = int(value)
    assert current is None and result, 'missing or truncated samples'
    return result


def summarize(rows):
    assert len(rows) >= 2, 'insufficient samples'
    first, last = rows[0], rows[-1]
    duration = last['time'] - first['time']
    non_cache = max(row['non_file_cache_estimate_bytes'] for row in rows)
    result = {
        'samples': len(rows), 'sampled_seconds': duration,
        'max_sample_gap_seconds': max(b['time']-a['time'] for a, b in zip(rows, rows[1:])),
        'charged_peak_bytes': max(row['memory.peak'] for row in rows),
        'sampled_current_peak_bytes': max(row['memory.current'] for row in rows),
        'sampled_non_file_cache_peak_bytes': non_cache,
        'sampled_non_file_cache_margin_basis_points': (CAP-non_cache)*10000//CAP,
        'sampled_file_cache_peak_bytes': max(row['file_cache_bytes'] for row in rows),
        'events_start': first['memory.events'], 'events_end': last['memory.events'],
        'events_delta': {k: last['memory.events'][k]-v for k, v in first['memory.events'].items()},
        'non_file_cache_estimate_end_bytes': last['non_file_cache_estimate_bytes'],
        'total_memory_headroom': 'TIGHT' if max(r['memory.peak'] for r in rows) > CAP*.8 else 'SAMPLED_MARGIN',
    }
    for kind in ('some', 'full'):
        delta = int(last['memory.pressure'][kind]['total'])-int(first['memory.pressure'][kind]['total'])
        assert delta >= 0
        result[kind+'_stall_seconds'] = delta/1e6
        result[kind+'_stall_percent'] = delta/1e4/duration
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence
    rows = samples((root/'samples.log').read_text(encoding='utf-8'))
    completed = json.loads((root/'completed.json').read_text(encoding='utf-8'))
    assert tuple(r['stage'] for r in completed) == STAGES
    pg = json.loads((root/'postgres.inspect.json').read_text(encoding='utf-8'))[0]
    pgid = pg['Id']
    assert pg['HostConfig']['NetworkMode'] == 'none'
    inspections = {}
    for stage in (*STAGES, 'postgres'):
        inspected = json.loads((root/(stage+'.inspect.json')).read_text(encoding='utf-8'))[0]
        host, state = inspected['HostConfig'], inspected['State']
        assert state['ExitCode'] == 0 and not state['OOMKilled'], (stage, state)
        assert host['Memory'] == host['MemorySwap'] == (CAP if stage == 'postgres' else 4*CAP)
        assert host['NanoCpus'] == (1500000000 if stage == 'postgres' else 2000000000)
        assert not host['PortBindings']
        if stage != 'postgres':
            assert host['NetworkMode'] == 'container:'+pgid
        inspections[stage] = {'image': inspected['Image'], 'state': state}
    metrics = summarize(rows)
    phases = {}
    for stage in STAGES:
        selected = [r for r in rows if r['phase'] == stage]
        assert selected, ('missing phase samples', stage)
        phases[stage] = summarize(selected) if len(selected) > 1 else {'samples': len(selected)}
    result = {'scope': 'LOCAL_SYNTHETIC_POSTGRESQL_PROFILE', 'overall': metrics,
              'phases': phases, 'completed': completed, 'containers': inspections,
              'limits': {'memory_bytes': CAP, 'swap_total_bytes': CAP, 'cpus': 1.5},
              'limitations': ['Sampled estimate is not an unsampled memory bound.',
                              'Total charged memory and cache pressure remain visible.',
                              'No accepted latency budget or NAS qualification.',
                              'Single publisher/reader workload; no concurrent backup qualification.']}
    (root/'report.json').write_bytes((json.dumps(result, indent=2)+'\n').encode())
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
