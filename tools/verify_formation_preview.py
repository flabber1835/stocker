"""Independent retained-trace and ledger checks; grants no input authority."""
import argparse
from collections import Counter
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def verify(root):
    with gzip.open(root / 'checkpoint.json.gz', 'rt', encoding='utf-8') as stream:
        cp = json.load(stream)
    assert cp['sha256'] == digest({k: v for k, v in cp.items() if k != 'sha256'})
    state = cp['state']
    assert cp['state_sha256'] == digest(state)
    assert cp['count'] == 126 and state['last_processed_session'] == '2026-07-31'
    seen, duplicates = {}, 0
    for filename in ('daily.jsonl', 'continuation.jsonl'):
        path = root / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            value = (row['session'], row['state_sha256'])
            if row['completed'] in seen:
                assert seen[row['completed']] == value, 'resumed state diverged'
                duplicates += 1
            seen[row['completed']] = value
    assert sorted(seen) == list(range(1, 127))
    assert seen[126][1] == cp['state_sha256']
    from sentinel.feed import calendar
    expected = calendar.previous_sessions('2026-07-31', 126)
    assert [seen[i][0] for i in range(1, 127)] == expected
    cash, shares, events = float(cp['plan']['capital']), {}, state['ledger']['events']
    for e in events:
        assert abs(e['cash_before'] - cash) < 1e-7
        if e['event_type'] in {'BUY', 'SELL'}:
            economic = -e['shares_delta'] * e['price'] - e['fees']
            assert abs(economic - e['cash_delta']) < 1e-7
        cash += e['cash_delta']
        assert abs(cash - e['cash_after']) < 1e-7
        if e['security_id']:
            sid = e['security_id']
            shares[sid] = shares.get(sid, Decimal(0)) + Decimal(str(e['shares_delta']))
    assert abs(cash - state['wealth_core']['cash']) < 1e-7
    actual = {}
    for e in state['wealth_core']['episodes'].values():
        sid = e['security_id']
        actual[sid] = actual.get(sid, Decimal(0)) + Decimal(str(e['current_shares']))
    assert {k: v for k, v in shares.items() if v} == actual
    longest = max(len(s['sessions']) for s in state['feed']['series'].values())
    assert longest <= 260
    return dict(status='MECHANICS_VERIFIED_NOT_ADMITTED', completed=126,
        first=expected[0], last=expected[-1], duplicate_rows_agree=duplicates,
        state_sha256=cp['state_sha256'], checkpoint_sha256=cp['sha256'],
        holdings=len(actual), shadow_cash=cash, shadow_nav=state['shadow_nav_history'][-1],
        exposure=state['last_decision']['target_core_exposure'],
        parent_exposure=state['last_decision']['champion_target_core_exposure'],
        owned=state['owned_impairment'], ledger_events=dict(Counter(e['event_type'] for e in events)),
        max_retained_sessions=longest, source=json.loads((root / 'source.json').read_text(encoding='utf-8')),
        note='Frozen earlier PIT-fixture policy; not the new current-information GO policy. No source-authority or deployment claim.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
