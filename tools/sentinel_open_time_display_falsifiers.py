"""Falsify callback display fences and interrupted transport in private processes."""
import argparse
import subprocess
import sys
from tools.sentinel_rolling_storage_falsifiers import child

CASES = {
    'deadline': ('s.callback_deadline_at>clock_timestamp()', 's.callback_deadline_at IS NOT NULL', 'expired'),
    'heartbeat': ("s.heartbeat_at>clock_timestamp()-INTERVAL '30 seconds'", 's.heartbeat_at IS NOT NULL', 'heartbeat'),
    'lease': ('l.expires_at>clock_timestamp()', 'l.expires_at IS NOT NULL', 'lease'),
    'fence': ('c.last_fence_token=l.fence_token', 'c.last_fence_token=c.last_fence_token', 'fence'),
    'certificate': ('c.certificate_sha256=a.certificate_sha256', 'c.certificate_sha256=c.certificate_sha256', 'certificate'),
    'state': ('c.state=%s AND s.state=%s', 'c.state=%s AND %s IS NOT NULL', 'state'),
    'kill': ("WHERE a.enabled AND NOT a.kill_switch_engaged AND a.authority_verdict='PASS'",
             "WHERE a.enabled AND a.authority_verdict='PASS'", 'kill'),
    'generation': (
        '"JOIN sentinel_automation_control a ON a.id=1 AND a.generation=l.control_generation "\n'
        '            "JOIN sentinel_automation_cycles c ON c.cycle_id=%s "\n'
        '            " AND c.control_generation=a.generation AND c.last_fence_token=l.fence_token "',
        '"JOIN sentinel_automation_control a ON a.id=1 "\n'
        '            "JOIN sentinel_automation_cycles c ON c.cycle_id=%s "\n'
        '            " AND c.last_fence_token=l.fence_token "', 'generation'),
}
MUTANTS = {name: ('sentinel.panel.sources', before, after,
    'test_only_exact_live_callback_lends_stale_observation_budget['+case+']')
    for name, (before, after, case) in CASES.items()}
MUTANTS['interrupted_transport'] = ('sentinel.panel.model',
    'if (index == 4 and interrupted_transport', 'if (index == 4 and False',
    'test_interrupted_callback_does_not_complete_order_transport[SUPERSEDED]')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        suffix = 'step_projection' if args.child == 'interrupted_transport' else 'callback_projection'
        return child(args.child, mutants=MUTANTS,
                     test_file='tests/sentinel/test_open_time_'+suffix+'.py')
    failed = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, '-m',
            'tools.sentinel_open_time_display_falsifiers', '--child', name],
            capture_output=True, text=True, check=False)
        killed = result.returncode == 1 and '1 failed' in result.stdout
        print(name + (': KILLED' if killed else ': NOT PROVED'), flush=True)
        if not killed:
            failed.append(name)
            print(result.stdout)
            print(result.stderr)
    return bool(failed)

if __name__ == '__main__':
    raise SystemExit(main())
