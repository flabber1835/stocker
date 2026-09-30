"""Summarize the actual completed research interval; optional standard plots."""
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import json
from pathlib import Path


def drawdown(values):
    peak=values[0]; worst=0.
    for value in values:
        peak=max(peak,value)
        worst=min(worst,value/peak-1)
    return worst


def summarize(root):
    result=json.loads((root/'result.json').read_text())
    raw=(root/'daily.jsonl').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=result['daily_sha256']:
        raise ValueError('daily results changed')
    rows=[json.loads(line) for line in raw.splitlines()]
    if not rows or any(a['session']>=b['session'] for a,b in zip(rows,rows[1:])):
        raise ValueError('empty or unordered daily results')
    for name,arm in result['arms'].items():
        if arm['sessions']!=len(rows) or arm['start']!=rows[0]['session'] or arm['end']!=rows[-1]['session']:
            raise ValueError('reported interval differs from daily results')
        values=[r['arms'][name]['equity'] for r in rows]
        valid=all(v is not None and v>0 for v in values)
        if valid!=arm['performance_available']:
            raise ValueError('performance availability differs')
        if valid and (abs(values[-1]/50_000-arm['multiple'])>1e-12
                      or abs(drawdown([50_000.]+values)-arm['maximum_drawdown'])>1e-12):
            raise ValueError('independent performance calculation differs')
    lines=['# Data-available research results','',
        f"Measured interval: {rows[0]['session']} to {rows[-1]['session']}; {len(rows)} sessions.",
        f"Status: {result['status']}. Starting cash: $50,000 per arm.",'',
        '| Variant | Final equity | Return | CAGR | Max drawdown | Fees | Blocked sessions |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name,a in result['arms'].items():
        money=f"${a['final_equity']:,.2f}" if a['final_equity'] is not None else 'unresolved'
        pct=lambda v:'unavailable' if v is None else f'{v:.2%}'
        lines.append(f"| {name} | {money} | {pct(a['multiple']-1 if a['multiple'] is not None else None)} | {pct(a['cagr'])} | {pct(a['maximum_drawdown'])} | ${a['fees']:,.2f} | {a['blocked_sessions']} |")
    lines+=['',f"SPY total-return comparison: {result['spy']['multiple']-1:.2%}; max drawdown {result['spy']['maximum_drawdown']:.2%}.",
        '', 'Unscaled Wealth Core research. No Sentinel overlay or live broker behaviour is measured.',
        'Retrospective source data and reviewed corporate-action terms are used in every arm.',
        'A complete historical path does not prove provider availability or automatic broker recovery.','']
    (root/'summary.md').write_text('\n'.join(lines),encoding='utf8')
    with (root/'yearly.csv').open('w',newline='',encoding='utf8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['year','variant','return','max_drawdown','fees','blocked_sessions'])
        writer.writeheader()
        for name in result['arms']:
            base=50_000.
            for year in sorted({r['session'][:4] for r in rows}):
                selected=[r['arms'][name] for r in rows if r['session'].startswith(year)]
                values=[r['equity'] for r in selected]
                good=base is not None and all(v is not None and v>0 for v in values)
                writer.writerow(dict(year=year,variant=name,
                    **{'return':values[-1]/base-1 if good else '',
                       'max_drawdown':drawdown([base]+values) if good else ''},
                    fees=sum(r['fees'] for r in selected),blocked_sessions=sum(r['blocked'] for r in selected)))
                base=values[-1]
    return result,rows


def plot(root,result,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(11,6))
    days=[date.fromisoformat(r['session']) for r in rows]
    for name in result['arms']:
        if result['arms'][name]['performance_available']:
            ax.plot(days,[r['arms'][name]['equity'] for r in rows],label=name,lw=1.5)
    ax.plot(days,[50_000*r['spy']/rows[0]['spy'] for r in rows],label='SPY total return',color='#555555',ls='--')
    ax.set(title='Data-available strategy research — no Sentinel overlay',ylabel='Portfolio value ($)',xlabel='Session')
    ax.grid(alpha=.2); ax.legend(); fig.tight_layout()
    fig.savefig(root/'comparison.png',dpi=160)
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--plot',action='store_true')
    args=parser.parse_args()
    result,rows=summarize(args.root)
    if args.plot:
        plot(args.root,result,rows)
    print((args.root/'summary.md').read_text())
