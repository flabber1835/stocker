"""Parse changed sources and reject new pyflakes findings against reviewed base."""
import ast
from collections import Counter
import io
from pathlib import Path
import subprocess

from pyflakes.api import check
from pyflakes.reporter import Reporter

BASE = 'b36fb1a63b56868bb1aa301b13df6d6ced6226a7'
FILES = [
    'sentinel/execution/feed_inputs.py', 'sentinel/feed/operational_snapshot.py',
    'sentinel/feed/rolling_go_inputs.py', 'sentinel/rolling_runtime.py',
    'sentinel/rolling_recovery.py', 'tests/sentinel/test_rolling_go_inputs.py',
    'tests/sentinel/test_rolling_report_consumers.py',
    'tests/sentinel/test_rolling_recovery_report_inputs.py',
    'audit/economic_399/rolling_status/run_local.py',
    'audit/economic_399/rolling_status/report_consumers/mutations.py',
    'audit/economic_399/rolling_status/report_consumers/static_check.py',
]


def findings(source, path):
    output = io.StringIO()
    check(source, path, Reporter(output, output))
    return Counter(line.split(': ', 1)[1] for line in output.getvalue().splitlines())


def main():
    for path in FILES:
        source = Path(path).read_text()
        ast.parse(source, filename=path)
        before = subprocess.run(['git', 'show', BASE+':'+path], capture_output=True, text=True)
        old = findings(before.stdout, path) if before.returncode == 0 else Counter()
        new = findings(source, path)
        assert not new-old, (path, new-old)
        print(path, 'syntax PASS, no new static findings; existing', sum(new.values()))


if __name__ == '__main__':
    main()
