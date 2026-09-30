"""Run behavioral tests against deliberately broken selective replay guards."""
import subprocess
import sys


CASES = [
    ("omit_alias_discovery", """
from sentinel.feed import source_aliases
source_aliases.discovery_symbols = lambda identity: ()
""", "test_discovery_scope_matches_full_oracle_and_reconstruction[unanchored]"),
    ("omit_competing_native", """
from sentinel.feed import source_aliases
real = source_aliases.discovery_symbols
source_aliases.discovery_symbols = lambda identity: tuple(s for s in real(identity) if s != 'OTHER_NATIVE')
""", "test_discovery_scope_matches_full_oracle_and_reconstruction[third_native]"),
    ("trust_matching_payload", """
import inspect, textwrap
from sentinel.feed import acquisition_parts as parts
body = textwrap.dedent(inspect.getsource(parts.Parts._manifest))
guard = 'if expected_generation is not None and manifest["generation"] != expected_generation:'
assert body.count(guard) == 1
exec(body.replace(guard, 'if expected_generation is not None:'), parts.__dict__)
parts.Parts._manifest = parts._manifest
""", "test_selected_generation_still_verifies_all_retained_prices"),
    ("trust_obsolete_manifest", """
import inspect, textwrap
from sentinel.feed import acquisition_parts as parts
body = textwrap.dedent(inspect.getsource(parts.Parts._manifest))
guard = 'if digest(manifest) != part_id or manifest.get("schema") != SCHEMA:'
assert body.count(guard) == 1
exec(body.replace(guard, 'if False:'), parts.__dict__)
parts.Parts._manifest = parts._manifest
""", "test_mismatched_generation_still_verifies_manifest_identity"),
]


def main():
    for label, mutation, target in CASES:
        script = mutation + "\nimport pytest\nraise SystemExit(pytest.main(" + repr([
            "tests/sentinel/test_daily_acquisition_work.py::" + target,
            "-q", "-p", "no:cacheprovider", "--tb=short", "--show-capture=no",
        ]) + "))\n"
        result = subprocess.run([sys.executable, "-c", script], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        if (result.returncode != 1 or "1 failed" not in result.stdout
                or "ERROR collecting" in result.stdout):
            raise AssertionError(f"{label} did not fail behaviorally:\n{result.stdout}")
        print(label + ": detected", flush=True)
    print(f"{len(CASES)} deliberate faults detected", flush=True)


if __name__ == "__main__":
    main()
