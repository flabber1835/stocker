"""Import-order regression for immediate emergency authority."""
from __future__ import annotations

import subprocess
import sys
import textwrap


def test_execution_first_import_does_not_leave_kill_serialized():
    program = textwrap.dedent(
        """
        import sentinel.execution
        from sentinel.automation import store

        assert store.engage_kill.__name__ == "engage_kill"
        assert store.engage_kill.__code__.co_freevars == ()
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        text=True, capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
