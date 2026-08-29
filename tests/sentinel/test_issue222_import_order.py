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


def _assert_immediate_authority_program(imports: str) -> str:
    return f"""
    {imports}
    from sentinel import authority
    from sentinel.automation import store

    functions = (
        store.engage_kill,
        authority.revoke_signed_certificate,
        authority.revoke_signed_key,
        authority.revoke_system_certificate,
    )
    for function in functions:
        assert function.__code__.co_freevars == (), (
            function.__name__, function.__code__.co_freevars)
    """


def test_execution_first_import_keeps_emergency_authority_immediate():
    _run(_assert_immediate_authority_program("import sentinel.execution"))


def test_automation_first_import_keeps_emergency_authority_immediate():
    _run(_assert_immediate_authority_program(
        "from sentinel.automation import store\nimport sentinel.execution"))
