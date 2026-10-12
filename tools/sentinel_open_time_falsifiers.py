"""Break market-open ownership/invalidation guards only in private processes."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    'gateway_proof_scope': (
        'sentinel.paper.execution',
        'with feed_inputs.pinned(conn, commit=False) as pinned, structural_verification.callback(conn):',
        'with feed_inputs.pinned(conn, commit=False) as pinned:',
        'test_gateway_warms_scope_before_constructing_guarded_broker'),
    'unknown_inventory': (
        'sentinel.structural_verification',
        'WHERE %s OR (cursor_name <> ALL(%s) AND NOT (cursor_name LIKE ANY(%s))) ',
        'WHERE %s AND (cursor_name <> ALL(%s) AND NOT (cursor_name LIKE ANY(%s))) ',
        'test_only_rolling_proof_ignores_exact_broker_records'),
    'dual_sizing_inventory': (
        'sentinel.structural_verification',
        "slot != 'rolling-checkpoint'", 'False',
        'test_only_rolling_proof_ignores_exact_broker_records'),
}

if __name__ == '__main__':
    raise SystemExit(main(mutants=MUTANTS,
        test_file='tests/sentinel/test_open_time_verification.py',
        runner='tools.sentinel_open_time_falsifiers'))
