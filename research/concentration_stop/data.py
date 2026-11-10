"""Immutable JSON/byte inventory only; no strategy, account or stop arithmetic."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

DAILY_BYTES = 170330724
DAILY_SHA = '9f1c682846167a1deafe4496aa4d2e6b803f5650d9f2265b34c691bae56067b2'
CHECKPOINT_SHA = '6942c696c752ee35d8a215a6ad138c71a69d9d8dd1337dcaa01519c3e141ea56'


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


def episode_key(ep):
    return str(ep['slot_id']) + '|' + str(ep['signal_date'])


def load_book(book):
    book = Path(book)
    need(file_sha(book/'checkpoint.json.gz') == CHECKPOINT_SHA, 'EXACT_SOURCE_CHECKPOINT')
    cp = json.loads(gzip.decompress((book/'checkpoint.json.gz').read_bytes()))
    raw = (book/'daily.jsonl').read_bytes()
    need(len(raw) == DAILY_BYTES and hashlib.sha256(raw).hexdigest() == DAILY_SHA,
         'EXACT_SOURCE_DAILY_PREFIX')
    rows = [json.loads(line) for line in raw.splitlines()]
    need(len(rows) == cp['completed'] == 2156 and rows[0]['session'] == '2018-01-02'
         and rows[-1]['session'] == '2026-07-31', 'EXACT_SOURCE_AXIS')
    need(cp['journals']['daily']['bytes'] == DAILY_BYTES
         and cp['journals']['daily']['prefix_sha256'] == DAILY_SHA, 'SOURCE_JOURNAL_BINDING')
    events = cp['run']['state']['ledger']['events']
    episodes = {}
    for index, row in enumerate(rows):
        audit = row['evidence']['research_entry_audit']
        breadth = row['evidence']['breadth']['holdings']
        for name, phase, output_name in [('opening_accounting', 'OPEN_BEFORE_FILLS', 'openings'),
                                         ('closing_accounting', 'CLOSE_AFTER_DECISION', 'observations')]:
            packet = audit[name]
            need(packet['session'] == row['session'] and packet['phase'] == phase,
                 'EXACT_SOURCE_PHASE')
            for ep in packet['wealth_core']['episodes'].values():
                key = episode_key(ep)
                if key not in episodes:
                    episodes[key] = dict(key=key, slot_id=ep['slot_id'], signal_date=ep['signal_date'],
                                         entry_date=ep['entry_date'], sids=[], tickers=[],
                                         anchor_held=ep['entry_date'] < rows[0]['session'],
                                         observations=[], openings=[])
                value = episodes[key]
                need(value['entry_date'] == ep['entry_date'], 'SOURCE_LINEAGE_ENTRY_DATE')
                if ep['security_id'] not in value['sids']:
                    value['sids'].append(ep['security_id'])
                if ep['ticker'] not in value['tickers']:
                    value['tickers'].append(ep['ticker'])
                price = packet['prices'].get(ep['security_id'], {})
                item = dict(index=index, session=row['session'], episode=ep,
                            price_status=price.get('status'), nav=row['economics']['parent_core_close_equity'])
                if output_name == 'observations':
                    metrics = [h for h in breadth if h['ticker'] == ep['ticker']]
                    item.update(raw_close=price.get('raw_price'),
                                own_dd=metrics[0]['own_dd'] if len(metrics) == 1 else None)
                else:
                    item['raw_open'] = price.get('raw_price')
                value[output_name].append(item)
    # The inventory is the observed measured lineage set, not an engine restore.
    episodes = {k: v for k, v in episodes.items() if v['observations']}
    need(len(episodes) == 201, 'ALL_201_SOURCE_LINEAGES')
    for ep in episodes.values():
        last = ep['observations'][-1]
        if last['index'] == len(rows)-1:
            ep['endpoint_session'], ep['endpoint_kind'] = rows[-1]['session'], 'END_MARK'
            ep['original_sell'] = None
        else:
            day = rows[last['index']+1]['session']
            sells = [e for e in events if e['event_type'] == 'SELL' and e['session'] == day
                     and e['security_id'] in ep['sids']]
            ep['endpoint_session'], ep['endpoint_kind'] = day, 'SELL' if len(sells) == 1 else 'CLOSED_OTHER'
            ep['original_sell'] = sells[0] if len(sells) == 1 else None
        ep['source_events'] = [e for e in events if e['security_id'] in ep['sids']
                               and ep['entry_date'] <= e['session'] <= ep['endpoint_session']]
    identity = dict(daily_sha256=DAILY_SHA, daily_bytes=DAILY_BYTES,
                    checkpoint_sha256=CHECKPOINT_SHA, checkpoint_outer_sha256=cp['sha256'],
                    closes=len(rows), lineages=len(episodes),
                    source_decisions_sha256=digest([r['decision'] for r in rows]))
    return dict(identity=identity, rows=rows, events=events, episodes=episodes)
