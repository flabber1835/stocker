"""Independent arithmetic audit of emitted daily NAV and month-end reports."""
import argparse
import csv
from datetime import date
from decimal import Decimal as D
import json
import math
from pathlib import Path

from sentinel.feed.calendar import sessions_in_range
from .inputs import START, END


def verify(root, *, complete=True):
    root = Path(root)
    days = [json.loads(line) for line in (root/'daily.jsonl').read_text().splitlines()]
    months = [json.loads(line) for line in (root/'monthly.jsonl').read_text().splitlines()]
    assert days and days[0]['session'] == START
    assert [row['session'] for row in days] == sessions_in_range(START, days[-1]['session'])
    if complete:
        assert len(days) == 5032 and days[-1]['session'] == END
    expected = {START, *(row['session'] for i, row in enumerate(days[:-1])
                           if row['session'][:7] != days[i+1]['session'][:7])}
    if days[-1]['session'] == END:
        expected.add(END)
    # A partial run may end exactly at a completed calendar month.
    assert expected.issubset({r['session'] for r in months})
    by_day = {row['session']:row for row in days}
    for row in months:
        assert row['session'] in by_day
        assert row['strategy'] == by_day[row['session']]['strategy']
        assert row['spy'] == by_day[row['session']]['spy']
    for name in ('strategy', 'spy'):
        base = D(days[0][name]['nav'])
        peak, drawdown = base, D(0)
        for row in days:
            value = D(row[name]['nav'])
            peak = max(peak, value)
            drawdown = max(drawdown, (peak-value)/peak)
            multiple = value/base
            elapsed = (date.fromisoformat(row['session'])-date.fromisoformat(START)).days
            assert abs(D(row[name]['multiple'])-multiple) < D('1e-24')
            assert abs(D(row[name]['maxdd'])-drawdown) < D('1e-24')
            if elapsed:
                annual = float(multiple)**(365.2425/elapsed)-1
                assert math.isclose(row[name]['cagr'], annual, rel_tol=1e-10, abs_tol=1e-12)
            else:
                assert row[name]['cagr'] is None
    audits = [json.loads(line) for line in (root/'terminal-audit.jsonl').read_text().splitlines()]
    assert [r['session'] for r in audits] == [r['session'] for r in days]
    assert all(a['counters'] == d['terminal_counters'] for a,d in zip(audits, days))
    with (root/'monthly.csv').open(newline='') as stream:
        exported = list(csv.DictReader(stream))
    assert [r['session'] for r in exported] == [r['session'] for r in months]
    for flat, row in zip(exported, months):
        for name in ('strategy', 'spy'):
            for key in ('cagr', 'multiple', 'maxdd'):
                actual = flat[name+'_'+key]
                value = row[name][key]
                assert actual == ('' if value is None else str(value))
    return dict(status='PASS', sessions=len(days), months=len(months), through=days[-1]['session'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.root, complete=not args.partial)))
