"""Falsify the new attribution and signal-unit diagnostics in isolated imports."""
import json
from pathlib import Path
import subprocess
import sys


FAULTS = {
    "omit_recovery_execution": ("begin, end = rows[start-1], rows[i+1]", "begin, end = rows[start-1], rows[i]"),
    "confuse_acceleration_with_volatility_level": ("loud_signal=volatility_acceleration(loud)", "loud_signal=rolling_std(loud, 20)"),
}


def main():
    results = {}
    for name, (before, after) in FAULTS.items():
        child = """
import sys, types
from pathlib import Path
import pytest
source=Path('research/owned55_replay/mechanics.py').read_text()
before, after = sys.argv[1:3]
assert source.count(before) == 1
module=types.ModuleType('research.owned55_replay.mechanics')
exec(compile(source.replace(before,after), '<isolated-diagnostic-fault>', 'exec'),module.__dict__)
sys.modules[module.__name__]=module
sys.exit(pytest.main(['research/owned55_replay/test_mechanics.py','-q','-p','no:cacheprovider']))
"""
        result = subprocess.run([sys.executable, "-c", child, before, after], capture_output=True, text=True)
        killed = result.returncode == 1 and "1 failed, 3 passed" in result.stdout
        results[name] = dict(killed=killed, exit_code=result.returncode,
                             test_summary=result.stdout.strip().splitlines()[-1:])
        if not killed:
            raise AssertionError(result.stdout+result.stderr)
    output = Path("audit/owned55-twenty-year/mechanics-mutations.json")
    output.write_bytes((json.dumps(results,indent=2)+"\n").encode())
    print(json.dumps(results))


if __name__ == "__main__":
    main()
