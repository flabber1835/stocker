"""Prove bounded-manifest guards with real PostgreSQL acceptance failures."""
import argparse
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

TEST = "tests/sentinel/test_backup_manifest_bound.py"
MUTANTS = {
    "overflow_byte": (
        "sentinel.backup_runtime_authority",
        "RUNTIME_MAX_MANIFEST_BYTES + 1,", "RUNTIME_MAX_MANIFEST_BYTES,",
        "test_valid_json_prefix_at_limit_cannot_hide_extra_bytes"),
    "parse_gate": (
        "sentinel.backup_runtime_authority",
        "CASE WHEN octet_length(bytes) <= %s", "CASE WHEN %s > 0",
        "test_oversize_invalid_bytes_are_refused_before_decoder_or_parser"),
    "binary_probe": (
        "sentinel.backup_runtime_authority",
        "SELECT pg_read_binary_file(%s,0,1,true)",
        "SELECT pg_read_file(%s,0,1048576,true)",
        "test_binary_presence_probe_does_not_split_valid_utf8"),
}


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
