"""Remove valuation/split guards in memory and require their falsifiers to fail."""
import argparse
import inspect
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=('nav', 'split'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.child:
        import pytest
        from research.impedance import pipeline_diagnostics as diagnostic
        from research.impedance import pipeline
        if args.child == 'nav':
            module, function = diagnostic, diagnostic.assert_nav
            old = "assert abs(value - recorded) < Decimal('0.000001'), (value, recorded)"
            test = 'test_nav_rejects_wrong_current_mark'
        else:
            module, function = pipeline, pipeline.assert_split_neutral
            old = "assert math.isclose(a[key],b[key],rel_tol=1e-11,abs_tol=1e-8), (a['day'],key,a[key],b[key])"
            test = 'test_split_equivalence_rejects_corruption[nav]'
        source = inspect.getsource(function)
        assert source.count(old) == 1
        namespace = dict(module.__dict__)
        exec(compile(source.replace(old, 'pass'), '<missing-economic-guard>', 'exec'), namespace)
        setattr(module, function.__name__, namespace[function.__name__])
        return int(pytest.main(['research/impedance/test_pipeline.py::' + test,
                               '-q', '-p', 'no:cacheprovider']))
    if args.output is None:
        parser.error('--output is required')
    results = []
    for name in ('nav', 'split'):
        proc = subprocess.run([sys.executable, '-m', 'research.impedance.pipeline_mutations', '--child', name],
                              text=True, capture_output=True, check=False)
        killed = proc.returncode == 1 and 'DID NOT RAISE' in proc.stdout and '1 failed' in proc.stdout
        results.append({'mutant': 'remove_' + name + '_guard', 'killed': killed,
                        'returncode': proc.returncode, 'output': proc.stdout + proc.stderr})
    args.output.write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps([{k:v for k,v in r.items() if k != 'output'} for r in results]))
    return 0 if all(r['killed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
