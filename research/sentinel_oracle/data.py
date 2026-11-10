"""Exact original P00 DATA authentication and inventory; no policy arithmetic."""
from __future__ import annotations

from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path

DAILY_BYTES = 170330724
DAILY_SHA = '9f1c682846167a1deafe4496aa4d2e6b803f5650d9f2265b34c691bae56067b2'
CHECKPOINT_SHA = '6942c696c752ee35d8a215a6ad138c71a69d9d8dd1337dcaa01519c3e141ea56'
OUTER_SHA = '352d3ad9c74d29d34faae0e07a1a592bc9b6921259a016298bd93e62c7188978'
LEVELS = ('0', '0.55', '1')


def need(value, code):
    if not value:
        raise ValueError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def allocation_code(value):
    parsed = Decimal(str(value))
    need(parsed.is_finite() and parsed in tuple(map(Decimal, LEVELS)), 'SOURCE_ALLOCATION_MENU')
    return tuple(map(Decimal, LEVELS)).index(parsed)


def load_source(book):
    book = Path(book)
    checkpoint_raw = (book/'checkpoint.json.gz').read_bytes()
    need(hashlib.sha256(checkpoint_raw).hexdigest() == CHECKPOINT_SHA, 'EXACT_ORIGINAL_CHECKPOINT')
    cp = json.loads(gzip.decompress(checkpoint_raw))
    raw = (book/'daily.jsonl').read_bytes()
    need(len(raw) == DAILY_BYTES and hashlib.sha256(raw).hexdigest() == DAILY_SHA,
         'EXACT_ORIGINAL_DAILY_BYTES')
    need(cp['sha256'] == OUTER_SHA and cp['completed'] == 2156
         and cp['journals']['daily']['bytes'] == DAILY_BYTES
         and cp['journals']['daily']['prefix_sha256'] == DAILY_SHA, 'CHECKPOINT_JOURNAL_BINDING')
    rows = [json.loads(line) for line in raw.splitlines()]
    axis = [row['session'] for row in rows]
    need(len(rows) == 2156 and axis[0] == '2018-01-02' and axis[-1] == '2026-07-31'
         and axis == sorted(set(axis)), 'EXACT_ORIGINAL_AXIS')
    need(rows[0]['economics']['held_allocation'] is None
         and rows[0]['economics']['strategy_nav'] == '50000'
         and rows[0]['economics']['net_factor'] == '1', 'UNFUNDED_FLAT_ANCHOR')
    need([i for i, row in enumerate(rows) if row['economics']['held_allocation'] is None] == [0]
         and [i for i, row in enumerate(rows) if 'formed_startup_marks' in row['economics']] == [1],
         'EXACT_FORMED_ENTRY_BOUNDARY')
    codes = []
    for i, row in enumerate(rows):
        e = row['economics']
        need(e['last_session'] == row['session'] and e['measurement_anchor_session'] == axis[0]
             and e['research_entry_mode'] == 'FORMED_BASKET', 'SOURCE_ACCOUNT_IDENTITY')
        need(all(name in e for name in ('parent_core_open_equity', 'parent_core_close_equity',
             'bil_open_adjusted', 'bil_close_adjusted', 'bil_previous_close_adjusted_current_publication',
             'strategy_prices', 'pending_allocation', 'held_allocation')), 'SOURCE_FACTOR_INPUTS')
        pending = allocation_code(e['pending_allocation'])
        need(pending == allocation_code(row['decision']['target_core_exposure']), 'SOURCE_CLOSE_TARGET')
        if i:
            code = allocation_code(e['held_allocation'])
            need(code == allocation_code(rows[i-1]['economics']['pending_allocation'])
                 and e['strategy_prices']['bil_previous_session'] == axis[i-1],
                 'SOURCE_NEXT_OPEN_CAUSAL_ALIGNMENT')
            codes.append(code)
    switches = sum(a != b for a, b in zip(codes, codes[1:]))
    need(len(codes) == 2155 and codes[0] == 2 and switches == 19,
         'FROZEN_BASELINE_ALLOCATION_CLASS')
    events = cp['run']['state']['ledger']['events']
    return dict(rows=rows, events=events, axis=axis, baseline_codes=codes,
        ordinary_switches=switches,
        identity=dict(daily_sha256=DAILY_SHA, daily_bytes=DAILY_BYTES,
            checkpoint_sha256=CHECKPOINT_SHA, checkpoint_outer_sha256=OUTER_SHA,
            source_decisions_sha256=digest([row['decision'] for row in rows]),
            closes=len(rows), start=axis[0], end=axis[-1],
            realized_allocation_choices=len(codes), ordinary_switches=switches))
