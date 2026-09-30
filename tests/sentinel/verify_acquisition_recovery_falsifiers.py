"""Demonstrate recovery tests reject broken guards, without editing source."""
import subprocess
import sys

cases = [
    ("unauthenticated_data", """
from sentinel.feed import source_corrections
source_corrections.hmac.compare_digest = lambda *_: True
""", "test_source_corrections.py::test_unsigned_coordinated_rewrite_cannot_become_authority"),
    ("unchecked_install_hash", """
import inspect
from sentinel.feed import corrections_cli as module
source = inspect.getsource(module.install)
line = 'identity != expected_sha256 or '
assert source.count(line) == 1
exec(source.replace(line, ''), module.__dict__)
""", "test_source_corrections.py::test_bad_install_or_retained_state_refuses[hash]"),
    ("source_wait_latches_activation", """
import inspect, textwrap
from sentinel.automation import service as module
source = textwrap.dedent(inspect.getsource(module.AutomationService._failure_diagnostic))
line = ' and not source_wait'
assert source.count(line) == 1
exec(source.replace(line, ''), module.__dict__)
module.AutomationService._failure_diagnostic = module._failure_diagnostic
""", "test_automation_service.py::test_data_wait_survives_retry_count_and_restart_then_executes_once"),
    ("missing_price_not_waited", """
import inspect, textwrap
from sentinel.feed.source_authority import coverage as module
source = textwrap.dedent(inspect.getsource(module.SeedCoverageAccumulator.require_complete))
line = 'if missing and not extra and not unresolved:'
assert source.count(line) == 1
exec(source.replace(line, 'if False:'), module.__dict__)
module.SeedCoverageAccumulator.require_complete = module.require_complete
""", "test_source_wait_recovery.py::test_missing_repeated_probe_then_reviewed_data_recovers_after_restart"),
    ("ready_dataset_repin", """
import inspect
from sentinel.feed import rolling_publisher as module
source = inspect.getsource(module._prepare)
line = 'corrections = pinned.get("source_corrections", source_corrections.bootstrap())'
assert source.count(line) == 1
exec(source.replace(line, 'corrections = None'), module.__dict__)
""", "test_source_wait_recovery.py::test_ready_resume_uses_sealed_corrections_even_if_active_install_is_unavailable[False]"),
]
for name, setup, test in cases:
    script = setup + "\nimport pytest, sys\nsys.exit(pytest.main(sys.argv[1:]))\n"
    result = subprocess.run([sys.executable, "-c", script, "tests/sentinel/" + test,
                             "-q", "--tb=short", "--show-capture=no", "-p", "no:cacheprovider"],
                            text=True, capture_output=True)
    if result.returncode != 1 or "1 failed" not in result.stdout or "ERROR collecting" in result.stdout:
        print(name, result.returncode, result.stdout, result.stderr, flush=True)
        raise SystemExit("falsifier did not detect its broken implementation")
    print("KILLED " + name, flush=True)
print(str(len(cases)) + " deliberately broken implementations detected", flush=True)
