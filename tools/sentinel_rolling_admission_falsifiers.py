"""Remove admission guards in memory; retain behavioral failures, not errors."""
import argparse
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

MUTANTS = {
    "issuer_binding": (
        "tools.sentinel_observation_authority",
        'warmup.get("strategy_identity_sha256") != claims["bindings"]["strategy_identity_sha256"]',
        'False',
        "test_offline_issuer_refuses_rehashed_evidence_for_different_strategy_or_corpus"),
    "reader_integrity": (
        "sentinel.feed.readers",
        'return publication.current(conn)\n    except publication.CorpusIncoherent as exc:\n        if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":',
        'return publication.current(conn)\n    except publication.CorpusIncoherent as exc:\n        if False:',
        "test_integrity_refusal_never_dispatches_to_a_different_reader"),
    "candidate_pin": (
        "sentinel.cli.authority",
        'with readers.pinned(conn, commit=False):',
        'with __import__("contextlib").nullcontext():',
        "test_public_candidate_cli_holds_one_generation_across_all_stages"),
    "warmup_binding": (
        "sentinel.observation_authority",
        'raise AuthorityRefused("observation warmup publication or strategy differs")',
        'pass',
        "test_candidate_refuses_warmup_for_different_generation_or_strategy[strategy_identity_sha256]"),
    "cache_generation": (
        "sentinel.feed.readers",
        'and item.get("detail") == publication_fingerprint(pub)',
        'and True', "test_readiness_cache_is_bound_to_authenticated_publication"),
    "provider_refresh_date": (
        "sentinel.observation_authority",
        '"snapshot_date": refreshed.astimezone(timezone.utc).date().isoformat()',
        '"snapshot_date": pub.window_end',
        "test_signed_rolling_candidate_installs_and_activates_with_reobserved_inputs"),
    "warmup_capital": (
        "sentinel.observation_authority",
        'cash = shadow_runtime._starting_cash(starting_cash)',
        'cash = shadow_runtime._starting_cash(starting_cash) + 1',
        "test_warmup_is_the_selected_canonical_production_transition"),
    "source_final_frontier": (
        "sentinel.feed.rolling_go_inputs",
        "PASS if material.session == target else FAIL", "PASS",
        "test_stale_readiness_is_a_failure_not_a_provider_retry_permission"),
}

TEST = "tests/sentinel/test_rolling_admission_readers.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        return child(args.child, mutants=MUTANTS, test_file=TEST)
    failed = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, "-m", __spec__.name, "--child", name],
                                capture_output=True, text=True, check=False)
        killed = result.returncode == 1 and "1 failed" in result.stdout
        print(name + (": KILLED" if killed else ": NOT PROVED"), flush=True)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        if not killed:
            failed.append(name)
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
