"""Run one broken implementation per process; no repository files are edited."""
import subprocess
import sys

cases = [
    ("action_repair_regresses_publication_frontier", """
import inspect
from sentinel.feed import actions_reconcile_v7
source = inspect.getsource(actions_reconcile_v7._cash_semantic_migration)
line = 'window_start=market_start, window_end=market_end,'
assert source.count(line) == 1
exec(source.replace(line, 'window_start=windows[0][0], window_end=windows[-1][1],'), actions_reconcile_v7.__dict__)
""", "test_maintenance_publication_frontier.py::test_historical_repair_preserves_the_published_frontier[action_economics]"),
    ("sep_repair_regresses_publication_frontier", """
import inspect
from sentinel.feed import maintenance
source = inspect.getsource(maintenance._reconcile_sep_mutations_core)
line = 'window_start=market_start, window_end=market_end,'
assert source.count(line) == 1
exec(source.replace(line, 'window_start=windows[0][0], window_end=windows[-1][1],'), maintenance.__dict__)
""", "test_maintenance_publication_frontier.py::test_historical_repair_preserves_the_published_frontier[sep_mutation]"),
    ("unproven_alias_publication_allowed", """
import inspect
from sentinel.feed import publication
source = inspect.getsource(publication.publish)
line = 'if source_aliases.KEY in merged and ('
assert source.count(line) == 1
exec(source.replace(line, 'if False and ('), publication.__dict__)
""", "test_alias_rejection_authority.py::test_publication_binds_the_exact_alias_evidence_proven_by_seed[missing_seed_proof]"),
    ("warmup_benchmark_axis_guard_disabled", """
import inspect
from sentinel import shadow_runtime
source = inspect.getsource(shadow_runtime._warmup_input_identity)
start = source.index('        spy = window.median5_spy_closes')
end = source.index('        for session in ordered:', start)
exec(source[:start] + source[end:], shadow_runtime.__dict__)
""", "test_warmup_economic_contract.py::test_warmup_identity_refuses_invalid_benchmark_before_hashing[middle]"),
    ("publication_alias_proof_guard_disabled", """
import inspect
from sentinel.feed import publication
source = inspect.getsource(publication.publish)
line = 'if proof["source_alias_rejections_sha256"] != aliases["sha256"]:'
assert source.count(line) == 1
exec(source.replace(line, 'if False:'), publication.__dict__)
""", "test_alias_rejection_authority.py::test_publication_binds_the_exact_alias_evidence_proven_by_seed[proof_hash]"),
    ("daily_native_presence_guard_disabled", """
import inspect, textwrap
from sentinel.feed import coherence
source = textwrap.dedent(inspect.getsource(coherence.StableSharadarFetch._validated_daily_listing_replay))
line = 'or item.permaticker in native_required'
assert source.count(line) == 1
exec(source.replace(line, ''), coherence.__dict__)
coherence.StableSharadarFetch._validated_daily_listing_replay = coherence._validated_daily_listing_replay
""", "test_alias_rejection_authority.py::test_daily_tolerance_cannot_replace_a_native_unit_with_its_unanchored_share[True]"),
    ("warmup_invents_cash", """
from sentinel.core import production
real = production.warm_session_state
def broken(*a, **k):
    state = real(*a, **k)
    state.wealth_core["cash"] += 1
    return state
production.warm_session_state = broken
""", "test_warmup_economic_contract.py::test_warmup_keeps_all_cash_and_creates_no_economic_history"),
    ("warmup_restart_loses_session", """
from sentinel.core.session import SessionState
real = SessionState.from_dict
def broken(cls, payload):
    state = real(payload)
    if state.feed.get("session_index") == 251:
        state.feed["session_index"] -= 1
    return state
SessionState.from_dict = classmethod(broken)
""", "test_warmup_economic_contract.py::test_first_and_second_closes_are_economically_identical_after_warmup_restart"),
    ("alias_rejection_disabled", """
from sentinel.feed import source_aliases
real = source_aliases.apply
source_aliases.apply = lambda identity, payload: real(identity, source_aliases.evidence())
""", "test_concurrent_source_symbols.py::test_early_discovery_preserves_native_authority_without_publication_permission"),
    ("native_price_guard_disabled", """
from sentinel.feed import source_aliases
source_aliases._valid_prices = lambda bars: True
""", "test_alias_rejection_authority.py::test_native_economics_cannot_hide_behind_population_tolerance[None-closeunadj]"),
    ("final_capture_validation_disabled", """
from sentinel.feed.source_authority import StableSharadarFetch
StableSharadarFetch.finalize_seed_capture = lambda *a, **k: None
""", "test_alias_capture_warmup.py::test_middle_collision_freezes_and_revalidates_every_capture_chunk[True]"),
    ("changed_source_rebuild_disabled", """
from sentinel.feed import source_aliases
source_aliases.require_current = lambda *a, **k: None
""", "test_alias_rejection_authority.py::test_corrected_source_requires_replay_and_empty_evidence_restores_native_identities"),
    ("cdc_excludes_unknown_symbols", """
from sentinel.feed import source_aliases
source_aliases.excludes = lambda *a, **k: True
""", "test_alias_rejection_authority.py::test_mutation_paths_share_the_same_explicit_exclusion_and_keep_unknowns_refused"),
    ("cdc_rejected_alias_not_recognized", """
from sentinel.feed import source_aliases
source_aliases.excludes = lambda *a, **k: False
""", "test_alias_rejection_authority.py::test_mutation_paths_share_the_same_explicit_exclusion_and_keep_unknowns_refused"),
    ("candidate_alias_evidence_leaks", """
from sentinel.feed import source_aliases
real = source_aliases.load
def broken(conn, *, include_run_id=None):
    if include_run_id is None:
        row = conn.execute("SELECT run_id FROM feed_ingest_runs WHERE publication_recovery ? %s ORDER BY started_at DESC LIMIT 1", (source_aliases.KEY,)).fetchone()
        if row:
            include_run_id = row[0]
    return real(conn, include_run_id=include_run_id)
source_aliases.load = broken
""", "test_concurrent_symbol_publication.py::test_empty_database_seed_restart_failed_correction_and_automatic_healing"),
    ("collision_guard_disabled", """
from sentinel.feed.source_authority import coverage
coverage.require_no_collisions = lambda *a, **k: None
""", "test_concurrent_source_symbols.py::test_all_observed_collisions_and_prices_survive_go_and_are_order_independent"),
    ("early_identity_check_disabled", """
from sentinel.feed.source_authority import StableSharadarFetch
StableSharadarFetch.preflight_seed_identity = lambda *a, **k: None
""", "test_concurrent_source_symbols.py::test_early_discovery_preserves_native_authority_without_publication_permission"),
    ("collision_probe_drops_symbols", """
import inspect
from sentinel.feed import source_probe
source = inspect.getsource(source_probe.require_recovery_probe)
fragment = ' | set(request.get("symbols", ()))'
assert source.count(fragment) == 2
exec(source.replace(fragment, ''), source_probe.__dict__)
""", "test_concurrent_source_symbols.py::test_worker_wait_keeps_all_symbols_and_corrected_metadata_permits_full_retry"),
    ("collision_probe_unbounded_read", """
import inspect
from sentinel.feed import source_probe
source = inspect.getsource(source_probe.require_recovery_probe)
line = 'return _bounded(fetch(table, params), 64)'
assert source.count(line) == 1
exec(source.replace(line, 'return fetch(table, params)'), source_probe.__dict__)
""", "test_concurrent_source_symbols.py::test_probe_stops_an_oversized_response_before_stability_materialization"),
    ("collision_probe_filters_bad_price", """
import inspect
from sentinel.feed import source_probe
source = inspect.getsource(source_probe.require_recovery_probe)
line = 'raise SourceDataPending("source membership probe has an invalid price row")'
assert source.count(line) == 1
exec(source.replace(line, 'continue'), source_probe.__dict__)
""", "test_concurrent_source_symbols.py::test_probe_checks_each_price_even_when_population_domain_floor_passes"),
    ("collision_is_terminal_failure", """
from sentinel import automation_runtime
from sentinel.feed.source_authority import SeedIdentityCollision
automation_runtime.REFRESH_TRANSIENT_FAILURES = tuple(
    cls for cls in automation_runtime.REFRESH_TRANSIENT_FAILURES if cls is not SeedIdentityCollision)
""", "test_concurrent_source_symbols.py::test_worker_wait_keeps_all_symbols_and_corrected_metadata_permits_full_retry"),
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
