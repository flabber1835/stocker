"""Independent date coverage and Decimal performance recomputation from retained traces."""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal as D
import gzip
import json
import math
from pathlib import Path

from research.bounded_20y.inputs import sha256
from sentinel.feed.calendar import previous_sessions
from .inputs import START, END


def performance(rows):
    axis = [d for d in previous_sessions(END, 6000) if d >= START]
    if [r['session'] for r in rows] != axis or len(rows) != 5032:
        raise ValueError('full-period measured coverage is incomplete, duplicated or reordered')
    if D(rows[0]['economics']['strategy_nav']) != 50000:
        raise ValueError('funded baseline differs from $50,000')
    years = D((date.fromisoformat(END)-date.fromisoformat(START)).days)/D('365.25')
    result = dict(start=START, end=END, measured_sessions=len(rows), years=str(years))
    for label, values in (
        ('combined', [D(r['economics']['strategy_nav']) for r in rows]),
        ('shadow_core', [D(r['economics']['parent_core_close_equity']) for r in rows]),
        ('spy', [D(str(r['spy'])) for r in rows])):
        if any(not x.is_finite() or x <= 0 for x in values):
            raise ValueError('nonpositive or nonfinite performance value')
        peak, drawdown = values[0], D(0)
        for value in values:
            peak = max(peak, value)
            drawdown = min(drawdown, value/peak-1)
        multiple = values[-1]/values[0]
        result[label] = dict(start_value=str(values[0]), end_value=str(values[-1]),
            multiple=str(multiple), cagr=math.expm1(math.log(float(multiple))/float(years)),
            maximum_drawdown=str(drawdown))
    # Rebuild account NAV from daily factors; do not take the final scalar as proof.
    nav = D(50000)
    for i,row in enumerate(rows):
        economics = row['economics']
        if abs(D(economics['previous_strategy_nav'])-nav) > D('.00000001'):
            raise ValueError('daily account continuity differs')
        factor = D(economics['net_factor'])
        if i == 0 and factor != 1:
            raise ValueError('first measured close earned a past return')
        nav *= factor
        if abs(D(economics['strategy_nav'])-nav) > D('.00000001'):
            raise ValueError('daily factor product differs from reported NAV')
    result['independent_factor_product_final_nav'] = str(nav)
    return result


def review(segments):
    committed, source = [], None
    references = []
    for directory in segments:
        identity = json.loads((directory/'identity.json').read_text())
        if source is None:
            source = identity['binding']
            if identity['resumed_from'] is not None:
                raise ValueError('first segment is already a continuation')
        elif identity['binding'] != source:
            raise ValueError('segments mix source or input identities')
        pointer = json.loads((directory/'latest-checkpoint.json').read_text())
        path = directory/pointer['path']
        if Path(pointer['path']).name != pointer['path'] or sha256(path) != pointer['sha256']:
            raise ValueError('checkpoint bytes differ')
        with gzip.open(path, 'rt') as f:
            packet=json.load(f)
        cursor = packet['state']['last_processed_session']
        if committed and packet['binding'] != source:
            raise ValueError('checkpoint binding differs')
        with (directory/'daily.jsonl').open() as f:
            for line in f:
                row=json.loads(line)
                if cursor is not None and row['session'] <= cursor:
                    committed.append(row)
        if committed and committed[-1]['chain'] != packet['chain']:
            raise ValueError('trace and checkpoint commitments differ')
        references.append(dict(segment=str(directory), checkpoint=pointer,
                               trace_sha256=sha256(directory/'daily.jsonl')))
    formation = [r for r in committed if r['phase'] == 'FORMATION']
    if [r['session'] for r in formation] != previous_sessions('2006-07-28',126):
        raise ValueError('126-session formation coverage differs')
    rows=[r for r in committed if r['phase'] == 'MEASURED']
    return dict(status='RESEARCH_COMPLETE_PENDING_ECONOMIC_REVIEW', source=source,
                performance=performance(rows), evidence=references)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--segments',type=Path,nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=review(args.segments)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result['performance'],sort_keys=True))
