"""Collection guard for tests/simulation/.

fuzz_test.py (and the *_sim.py harnesses) are operational SCRIPTS that fire
live HTTP at the running compose stack from module level — importing them IS
running them. Bare `pytest` used to execute the fuzzer during collection and
fail the whole run whenever Docker wasn't up (external audit finding #8).
Run them explicitly instead:

    python tests/simulation/fuzz_test.py

The test_*.py files in this directory are ordinary pytest modules and remain
collected.
"""
collect_ignore = [
    "fuzz_test.py",
    "share_class_dedup_test.py",   # *_test.py pattern would collect it too
]
