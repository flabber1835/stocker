"""Prove pressure-report oracles reject false margin, shared-memory and OOM claims."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
REL = Path('audit/economic_399/postgres_pressure/report.py')
TEST = Path('tests/sentinel/test_postgres_pressure_evidence.py')
MUTANTS = {
    'shared_memory_omitted': ("stat['anon'] + stat['shmem'] + stat['kernel']",
                              "stat['anon'] + stat['kernel']"),
    'pressure_called_margin': ("'TIGHT' if max(r['memory.peak'] for r in rows) > CAP*.8 else 'SAMPLED_MARGIN'",
                              "'SAMPLED_MARGIN'"),
    'oom_ignored': ("assert all(events[k] == 0 for k in ('oom', 'oom_kill', 'oom_group_kill')), events",
                    'pass  # deliberately broken OOM guard'),
}


def main():
    original = (ROOT/REL).read_text(encoding='utf-8')
    for name, (old, new) in MUTANTS.items():
        assert original.count(old) == 1, name
        with tempfile.TemporaryDirectory(prefix='pressure-mutant-') as directory:
            temp = Path(directory)
            destination = temp/REL
            destination.parent.mkdir(parents=True)
            destination.write_text(original.replace(old, new), encoding='utf-8')
            for parent in (destination.parent, *list(destination.parents)[1:3]):
                (parent/'__init__.py').touch()
            (temp/'test_pressure.py').write_bytes((ROOT/TEST).read_bytes())
            env = {**os.environ, 'PYTHONPATH': str(temp), 'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, '-m', 'pytest', 'test_pressure.py',
                                     '-q', '--tb=short', '-p', 'no:cacheprovider'],
                                    cwd=temp, env=env, capture_output=True, text=True)
            print(name, result.returncode, result.stdout, result.stderr, flush=True)
            assert result.returncode == 1 and 'failed' in result.stdout, name
    print('3/3 intended pressure-report mutants detected', flush=True)


if __name__ == '__main__':
    main()
