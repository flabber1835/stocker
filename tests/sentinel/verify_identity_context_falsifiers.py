"""Run one broken implementation per process; no repository files are edited."""
import subprocess
import sys

cases = [
    ("undated_anchor_join", """
from sentinel.feed import symbol_lineage
symbol_lineage.Occurrences.anchor_applies = lambda *args: True
""", "test_reused_symbol_identity.py::test_unrelated_later_reuse_cannot_poison_or_capture_phge[restated-metadata]"),
    ("unbounded_reused_alias", """
from sentinel.feed import symbol_lineage
symbol_lineage.Occurrences.alias_interval = lambda self, symbol, window, first, last, **kw: (first, last)
""", "test_reused_symbol_identity.py::test_unrelated_later_reuse_cannot_poison_or_capture_phge[restated-complete-actions]"),
    ("missing_claim_guard", """
import inspect
from sentinel.feed import symbol_identity
source = inspect.getsource(symbol_identity.SymbolProjection)
assert source.count('if (claims !=') == 1
exec(source.replace('if (claims !=', 'if False and (claims !='), symbol_identity.__dict__)
""", "test_historical_symbol_identity.py::test_damaged_older_claims_do_not_grant_a_partial_alias[missing-older-to]"),
    ("probe_omits_competing_metadata", """
import inspect
from sentinel.feed import source_probe
source = inspect.getsource(source_probe.require_recovery_probe)
start = source.index('        ticker_params =')
end = source.index('        for field in', start)
exec(source[:start] + source[end:], source_probe.__dict__)
""", "test_exported_symbol_identity.py::test_cheap_retry_cannot_hide_conflicting_context_from_full_projection"),
    ("preflight_disabled", """
from sentinel.feed import source_authority
source_authority.StableSharadarFetch.preflight_seed_membership = lambda *a, **k: None
""", "test_exported_symbol_identity.py::test_production_capture_rebuild_and_publication_with_complete_history[missing-last-price]"),
    ("diagnostic_dropped", """
from sentinel import source_diagnostic
source_diagnostic.coverage_diagnostic = lambda raw: None
""", "test_source_coverage_diagnostic.py::test_real_conflict_survives_both_preparation_markers_and_bundle_view"),
    ("context_exception_sampled", """
import inspect, textwrap
from sentinel.feed.source_authority import fetch
source = textwrap.dedent(inspect.getsource(fetch.StableSharadarFetch.preflight_seed_membership))
line = 'sessions = [session for session in sessions if session not in contextual]'
assert source.count(line) == 1
exec(source.replace(line, 'pass'), fetch.__dict__)
fetch.StableSharadarFetch.preflight_seed_membership = fetch.preflight_seed_membership
""", "test_seed_membership_sample.py::test_context_dependent_onset_exception_stays_with_full_capture"),
]
selected = [case for case in cases if not sys.argv[1:] or case[0] in sys.argv[1:]]
if not selected or set(sys.argv[1:]) - {case[0] for case in cases}:
    raise SystemExit("unknown falsifier selection")
for name, setup, test in selected:
    script = setup + "\nimport pytest, sys\nsys.exit(pytest.main(sys.argv[1:]))\n"
    result = subprocess.run([sys.executable, "-c", script, "tests/sentinel/" + test,
                             "-q", "--tb=short", "-p", "no:cacheprovider"],
                            text=True, capture_output=True)
    if result.returncode != 1 or "1 failed" not in result.stdout or "ERROR collecting" in result.stdout:
        print(name, result.returncode, result.stdout, result.stderr, flush=True)
        raise SystemExit("falsifier did not detect its broken implementation")
    print("KILLED " + name, flush=True)
print(str(len(selected)) + " deliberately broken implementations detected", flush=True)
