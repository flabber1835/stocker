"""Import-order regression for immediate emergency authority."""
from __future__ import annotations

import subprocess
import sys
import textwrap


def _run(program: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(program)],
        text=True, capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr or result.stdout


def test_execution_first_import_keeps_emergency_authority_native():
    _run("""
        import sentinel.execution
        from sentinel import authority
        from sentinel.automation import store

        functions = (
            store.engage_kill,
            authority.revoke_signed_certificate,
            authority.revoke_signed_key,
            authority.revoke_system_certificate,
        )
        assert all("alpaca_remediation" not in f.__module__ for f in functions)
    """)


def test_automation_first_import_does_not_replace_emergency_authority():
    _run("""
        from sentinel import authority
        from sentinel.automation import store

        baseline = (
            store.engage_kill,
            authority.revoke_signed_certificate,
            authority.revoke_signed_key,
            authority.revoke_system_certificate,
        )
        import sentinel.execution
        current = (
            store.engage_kill,
            authority.revoke_signed_certificate,
            authority.revoke_signed_key,
            authority.revoke_system_certificate,
        )
        assert current == baseline
    """)
