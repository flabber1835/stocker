"""Falsify bounded canonical encoding without changing files on disk."""
from tools.sentinel_rolling_storage_falsifiers import main


MUTANTS = {
    "nonfinite_hash": ("sentinel.core.session", "allow_nan=False", "allow_nan=True",
        "test_hash_still_rejects_non_json_after_single_pass_validation"),
    "record_string_bound": ("sentinel.core.session",
        "kind is str and len(item) <= 64", "kind is str",
        "test_bounded_record_encoding_does_not_admit_oversized_strings"),
}


if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS,
        test_file="tests/sentinel/test_state_hash_allocations.py",
        runner="tools.sentinel_canonical_state_falsifiers"))
