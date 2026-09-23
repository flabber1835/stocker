"""Compare actual pytest collections, independent of the partition classifier."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def collect(arguments):
    command = [sys.executable, *arguments, '--collect-only', '-q', '-p', 'no:cacheprovider']
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    nodes = [line.strip() for line in result.stdout.splitlines()
             if line.startswith('tests/sentinel/') and '::' in line]
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError('empty or duplicate pytest collection')
    return sorted(nodes)


def main():
    all_nodes = collect(['-m', 'pytest', 'tests/sentinel'])
    report = {'complete': False, 'baseline': all_nodes, 'partitions': {}}
    joined = []
    for name in ('general', 'rolling', 'warmup', 'automation'):
        nodes = collect(['tools/sentinel_test_partition.py', name])
        report['partitions'][name] = nodes
        joined.extend(nodes)
    if sorted(joined) != all_nodes:
        raise ValueError('partition union differs from the independent full collection')
    report['complete'] = True
    print(json.dumps({
        'complete': True, 'baseline_count': len(all_nodes),
        'partitions': {name: len(nodes) for name, nodes in report['partitions'].items()},
        'full_collection_sha256': hashlib.sha256('\n'.join(all_nodes).encode()).hexdigest(),
        'duplicate_nodes': len(joined) - len(set(joined)),
        'missing_nodes': len(set(all_nodes) - set(joined)),
    }, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
