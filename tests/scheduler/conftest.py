import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "scheduler"))

# ── apscheduler stubs ────────────────────────────────────────────────────────
# app.main imports apscheduler at module scope and the package is not a test
# dependency, so every scheduler test module needs it stubbed BEFORE it imports
# app.main.
#
# This used to live inside test_supervisor.py, which made collection depend on
# ALPHABETICAL TEST ORDERING: any module sorting before "test_supervisor" hit a
# real ModuleNotFoundError, while the same file collected fine as part of the
# full directory run. A test suite whose importability depends on filenames is a
# trap for the next person adding a file, so the stub belongs here — conftest
# runs before every module regardless of name.
#
# setdefault throughout, so a real apscheduler (if ever installed) wins and
# test_supervisor's own call remains a harmless no-op.
import types
from unittest.mock import MagicMock


def _stub_apscheduler() -> None:
    asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    asyncio_mod.AsyncIOScheduler = MagicMock()
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    cron_mod.CronTrigger = MagicMock()
    interval_mod = types.ModuleType("apscheduler.triggers.interval")
    interval_mod.IntervalTrigger = MagicMock()
    for name, mod in (
        ("apscheduler", types.ModuleType("apscheduler")),
        ("apscheduler.schedulers", types.ModuleType("apscheduler.schedulers")),
        ("apscheduler.schedulers.asyncio", asyncio_mod),
        ("apscheduler.triggers", types.ModuleType("apscheduler.triggers")),
        ("apscheduler.triggers.cron", cron_mod),
        ("apscheduler.triggers.interval", interval_mod),
    ):
        sys.modules.setdefault(name, mod)


_stub_apscheduler()
