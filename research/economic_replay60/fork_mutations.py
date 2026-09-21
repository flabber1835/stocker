"""Isolated falsifiers for the one-time analytical source-fork fences."""
import argparse
import inspect
import json
from pathlib import Path
import subprocess
import sys
import uuid

CASES = {
    'source_fence': ('changed_files != {', 'False and changed_files != {',
                     'test_modified_controller_source_refuses'),
    'revision_fence': ('if args.revision != "ee23c894c97a2c4023654ce3a56a62728f5b061e":',
                       'if False:', 'test_unreviewed_revision_refuses'),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=CASES)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    if args.child:
        import pytest
        from research.economic_replay60 import fork_430 as module
        old, new, test = CASES[args.child]
        source = inspect.getsource(module.main)
        assert source.count(old) == 1
        # Preserve the module globals so the fixture can stop at the verified
        # boundary; import/setup failures must not count as killed mutations.
        exec(compile(source.replace(old, new), '<fork-mutant>', 'exec'), module.__dict__)
        return int(pytest.main(['research/economic_replay60/test_fork_430.py::'+test,
            '-q', '-p', 'no:cacheprovider', '--basetemp', str(args.scratch/uuid.uuid4().hex)]))
    rows = []
    for name in CASES:
        proc = subprocess.run([sys.executable, '-m', 'research.economic_replay60.fork_mutations',
            '--child', name, '--scratch', str(args.scratch)], capture_output=True, text=True)
        killed = (proc.returncode == 1 and '1 failed' in proc.stdout
                  and 'ReachedVerifiedBoundary' in proc.stdout)
        rows.append(dict(name=name, killed=killed, output=proc.stdout+proc.stderr))
        print(name, 'KILLED' if killed else 'NOT KILLED')
    args.output.write_text(json.dumps(rows, indent=2)+'\n', encoding='utf-8', newline='\n')
    return 0 if all(row['killed'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
