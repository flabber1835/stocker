"""Guard-removal controls, run only in the disposable repository copy."""
from pathlib import Path
import argparse
import subprocess
import sys


def main():
    assert Path.cwd() == Path('/tmp/repo') and Path('/source').is_dir()
    cases = {
        'complete-genesis': ('sentinel/shadow_observation.py', 'AND state=%s::jsonb',
            "AND state->>'genesis_sha256'=(%s::jsonb)->>'genesis_sha256'",
            'test_database_genesis_comparison_checks_complete_payload_and_row_session'),
        'row-session': ('sentinel/shadow_observation.py', 'SELECT session::text=%s AND',
            'SELECT %s::text IS NOT NULL AND',
            'test_database_genesis_comparison_checks_complete_payload_and_row_session'),
        'seed-release': ('sentinel/shadow_observation.py', '            self.initial_state = None',
            '            pass', 'test_read_only_verifier_releases_seed_and_cannot_be_reused'),
        'consumed-refusal': ('sentinel/shadow_observation.py', 'if getattr(self, "_consumed_for_status", False):',
            'if False:', 'test_read_only_verifier_releases_seed_and_cannot_be_reused'),
        'status-routing': ('sentinel/rolling_runtime.py', '_closure(conn, context, status_only=True)',
            '_closure(conn, context, status_only=False)', 'test_daily_checkpoint_verifies_history_once'),
        'stream-completeness': ('sentinel/shadow_observation.py', '                    series[key] = item',
            '                    series[key] = item\n                    break',
            'test_streamed_record_spans_multiple_batches'),
        'snapshot-identity': ('sentinel/shadow_observation.py',
            'if cur.fetchone() != (self._status_snapshot_time, "on", "repeatable read"):',
            'if False:', 'test_status_snapshot_cannot_be_reused_across_transactions'),
        'snapshot-readonly': ('sentinel/shadow_observation.py',
            'if readonly != "on" or isolation != "repeatable read":',
            'if False:', 'test_status_snapshot_cannot_be_reused_across_transactions'),
        'suffix-inventory': ('sentinel/shadow_observation.py',
            'if len(inventory) > 1:', 'if False:',
            'test_streamed_status_refuses_excess_suffix_before_payloads'),
        'decoder-lifetime': ('sentinel/shadow_observation.py',
            '            self.loads = _compact_json_decoder()',
            '            self.loads = _compact_json_decoder()\n            type(self)._retained = self.loads',
            'test_cursor_decoder_cache_is_released_and_connection_unchanged[False]'),
    }
    failed = []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=cases)
    selected = parser.parse_args().case
    for name, (path, old, new, test) in cases.items():
        if selected and name != selected:
            continue
        command = [sys.executable, '-m', 'pytest', 'tests/sentinel/test_status_memory.py::'+test,
                   '-q', '--tb=short', '-p', 'no:cacheprovider']
        baseline = subprocess.run(command, capture_output=True, text=True, timeout=180)
        print(name+' baseline:', baseline.stdout, baseline.stderr, flush=True)
        assert baseline.returncode == 0 and '1 passed' in baseline.stdout
        source = Path(path)
        original = source.read_bytes()
        text = original.decode()
        assert text.count(old) == (2 if name in ('consumed-refusal', 'decoder-lifetime') else 1), name
        try:
            source.write_bytes(text.replace(old, new, 1).encode())
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            killed = result.returncode == 1 and '1 failed' in result.stdout
            print(name+(': KILLED' if killed else ': NOT PROVED'), flush=True)
            print(result.stdout, result.stderr, flush=True)
            if not killed:
                failed.append(name)
        finally:
            source.write_bytes(original)
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
