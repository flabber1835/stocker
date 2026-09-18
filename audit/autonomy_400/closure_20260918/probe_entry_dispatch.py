"""Inspect effective installer overlays in a fresh pinned interpreter.

Usage: PYTHONPATH=<pinned>/scripts:<pinned> python probe_entry_dispatch.py [mode]
This imports source and installs in-memory overlays. It creates no deployment,
configuration, account, registry or database state.
"""
import inspect
import json
import sys

import sentinel_autonomous_deploy_entry as entry

mode = None if len(sys.argv) == 1 else sys.argv[1]
entry.install_runtime_guards(mode)
entry.bootstrap._install_wallclock_independent_dual_overlay()
cls = entry.bootstrap.BootstrapDeploy
methods = {}
for name, value in inspect.getmembers(cls):
    if not inspect.isfunction(value):
        continue
    path = inspect.getsourcefile(value)
    if path is None:
        continue
    methods[name] = {
        'qualified_name': value.__qualname__,
        'source_file': path,
        'line': inspect.getsourcelines(value)[1],
    }
print(json.dumps({
    'requested_mode': mode,
    'deploy_mro': [f'{c.__module__}.{c.__qualname__}' for c in cls.__mro__],
    'config_mro': [f'{c.__module__}.{c.__qualname__}' for c in entry.bootstrap.hardened.Config.__mro__],
    'methods': methods,
}, indent=2))
