#!/usr/bin/env python3
"""Run current harness tests against the exact pre-extraction runtime API."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LEGACY_SHA = '887f479b15ad861313da666ad698034d3847121c'


def install_legacy_import_bridge() -> dict:
    """Expose the original transition and dataclasses at their extracted names.

    Module aliases preserve function globals and plan-capture instrumentation.
    The adapter is restricted to the frozen, authenticated legacy source tree.
    """
    runtime = ROOT / 'main-src'
    observed = subprocess.check_output(
        ['git', '-C', str(runtime), 'rev-parse', 'HEAD'], text=True).strip()
    if observed != LEGACY_SHA:
        raise RuntimeError(f'legacy runtime bridge SHA mismatch: {observed}')
    if importlib.util.find_spec('sentinel.core.kernel') is not None:
        raise RuntimeError('legacy runtime unexpectedly includes extracted kernel')
    if importlib.util.find_spec('sentinel.core.session') is not None:
        raise RuntimeError('legacy runtime unexpectedly includes extracted session types')
    from sentinel.core import production
    expected = runtime / 'sentinel/core/production.py'
    if Path(production.__file__).resolve() != expected.resolve():
        raise RuntimeError(f'production module escaped frozen runtime: {production.__file__}')
    required = ('advance_state', 'plan_session', 'session_breadth',
                'SessionState', 'PublishedSession', 'FeedAnchor')
    for name in required:
        if not hasattr(production, name):
            raise RuntimeError(f'frozen runtime API missing: {name}')
    production.advance_session = production.advance_state
    sys.modules['sentinel.core.kernel'] = production
    sys.modules['sentinel.core.session'] = production
    import sentinel.core
    sentinel.core.kernel = production
    sentinel.core.session = production
    return {'runtime_sha': observed, 'transition': 'sentinel.core.production.advance_state',
            'module': str(expected), 'adapter': 'IMPORT_NAMES_ONLY'}


def main() -> int:
    import json
    print('[PINNED_RUNTIME_BRIDGE] ' + json.dumps(install_legacy_import_bridge(), sort_keys=True), flush=True)
    if len(sys.argv) < 2 or sys.argv[1] not in {'tests', 'future'}:
        raise SystemExit('usage: research_pinned_suite.py {tests|future} [arguments]')
    operation = sys.argv[1]
    arguments = sys.argv[2:]
    if operation == 'tests':
        import pytest
        return int(pytest.main(arguments))
    from backtester import future_leak_certification
    sys.argv = ['future_leak_certification.py', *arguments]
    return int(future_leak_certification.main())


if __name__ == '__main__':
    raise SystemExit(main())
