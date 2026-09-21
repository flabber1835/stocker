"""Verify the comparison's two new trust-boundary checks really fail broken."""
import argparse
import inspect
import json
from pathlib import Path
import subprocess
import sys
import uuid

CASES = {
    'identity': ('restore', "snapshot['identity'] != self.identity", 'False',
                 'test_research_snapshot_refuses_cross_parameter_identity'),
    'parity': ('assert_baseline', "result['target'] == row['core_multiplier']", 'True',
               'test_parity_guard_detects_target_divergence'),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=CASES)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    if args.child:
        import pytest
        from research.impedance import parameters as module
        name, old, new, test = CASES[args.child]
        owner = module.ProbeController if name == 'restore' else module
        import textwrap
        source = textwrap.dedent(inspect.getsource(getattr(owner, name)))
        assert source.count(old) == 1
        namespace = dict(module.__dict__)
        exec(compile(source.replace(old, new), '<probe-mutant>', 'exec'), namespace)
        setattr(owner, name, namespace[name])
        return int(pytest.main([f'research/impedance/test_parameters.py::{test}', '-q',
            '-p', 'no:cacheprovider', '--basetemp', str(args.scratch/uuid.uuid4().hex)]))
    results = []
    for name in CASES:
        process = subprocess.run([sys.executable, '-m', 'research.impedance.parameter_mutations',
            '--child', name, '--scratch', str(args.scratch)], capture_output=True, text=True)
        killed = process.returncode == 1 and 'DID NOT RAISE' in process.stdout
        results.append(dict(name=name, killed=killed, output=process.stdout+process.stderr))
        print(name, 'KILLED' if killed else 'SURVIVED', flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8', newline='\n')
    return 0 if all(r['killed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
