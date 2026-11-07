"""Factual seven-event hydration, detached from strategy and financial state."""
from dataclasses import asdict
import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_remainder_input import CATALOG, PRIVATE, ORDINARY, SCHEMA, digest, sha

EXPECTED = {
    'DFS': ('884366050981445610', '2025-05-16', '2025-05-19', 'CANONICAL_ORDINARY'),
    'BPMC': ('142211284179578270', '2025-07-17', '2025-07-18', 'CVR_RANGE'),
    'ETNB': ('146334772721825722', '2025-10-30', '2025-10-30', 'CVR_RANGE'),
    'CDTX': ('1113557341267806383', '2026-01-06', '2026-01-07', 'CANONICAL_ORDINARY'),
    'RAPT': ('117211213247402731', '2026-03-03', '2026-03-03', 'CANONICAL_ORDINARY'),
    'SLNO': ('736275735073520563', '2026-05-18', '2026-05-18', 'CANONICAL_ORDINARY'),
    'TMHC': ('13062188894457483', '2026-07-23', '2026-07-27', 'UNOWNED_CLOSING_DAY_CASH_SENSOR'),
}


def validate(catalog):
    need(catalog['schema'] == 'research.p02-remainder-terminal-catalog/1'
         and catalog['unchanged_original_models'] == 8
         and all(catalog[k] is False for k in ('canonical_financial_source_changed',
             'production_contacted', 'diagnostic_state_adopted')),
         'REMAINDER_DISTINCT_FACT_INPUT_WITHOUT_SOURCE_OR_STATE_CONVERSION')
    actual = {v['ticker']: (v['security_id'], v['native_session'], v['core_session'], v['treatment'])
              for v in catalog['cases']}
    need(len(catalog['cases']) == 7 and actual == EXPECTED, 'REMAINDER_EXACT_SEVEN_UNCONSUMED_EVENTS')
    by = {v['ticker']: v for v in catalog['cases']}
    need(by['BPMC']['consideration_bounds'] == ['129', '135']
         and by['ETNB']['consideration_bounds'] == ['14.50', '20.50']
         and all('added' not in by[k] for k in ('BPMC', 'ETNB')),
         'REMAINDER_CVR_FULL_RANGES_WITHOUT_POINT_VALUATION')
    for ticker, cash in (('CDTX', 221.50), ('RAPT', 58.0), ('SLNO', 53.0), ('TMHC', 72.50)):
        case = by[ticker]
        need(case['added']['cash_per_share'] == cash and case['added']['kind'] == 'CASH_MERGER'
             and case['added']['session'] == case['core_session']
             and case['added']['security_id'] == case['security_id']
             and case['added']['entitlement_aggregation'] == 'HOLDER'
             and all(case['added'][k] is None for k in ('delivered_security_id', 'delivered_ticker',
                 'delivered_issuer_id', 'exchange_ratio', 'cash_in_lieu_price_per_delivered_share')),
             'REMAINDER_EXACT_MANDATORY_COMMON_CASH_AND_NO_UNUSED_STOCK_TERMS')
    dfs = by['DFS']['added']
    need(dfs['kind'] == 'CONVERSION' and dfs['cash_per_share'] is None
         and dfs['exchange_ratio'] == '1.0192' and dfs['delivered_security_id'] == '326864109633904206'
         and dfs['delivered_ticker'] == 'COF' and dfs['delivered_issuer_id'] == 'SEC_CIK:927628'
         and dfs['cash_in_lieu_price_per_delivered_share'] is None,
         'REMAINDER_DFS_EXACT_STOCK_RATIO_WITHOUT_INVENTED_CIL')
    need(by['TMHC']['sensor_session'] == '2026-07-24'
         and by['TMHC']['public_information_accepted_at'] == '2026-07-24T16:00:24-04:00'
         and by['TMHC']['event_quote'] == dict(present=False, row_sha256=None, split_ratio='1')
         and by['TMHC']['consideration_bounds'] == ['72.50', '72.50'],
         'REMAINDER_TMHC_SEPARATE_KNOWN_CASH_RIGHT_WITHOUT_FABRICATED_CLOSE')
    return catalog


def hydrate(cp, old, out):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    catalog = validate(json.loads((Path(__file__).parent / CATALOG).read_bytes()))
    need(cp['source_cursor'] == '2025-04-30' and cp['completed'] == 1842
         and len(cp['repairs']) == 41, 'REMAINDER_ONLY_VERIFIED_STRICT_OWN41')
    actions, dates = inputs.load_actions(Path('/frozen/bundle')), axis()
    natives, keys = {}, {}
    for case in catalog['cases']:
        sid, native_day = case['security_id'], case['native_session']
        native, = [v for v in actions.terminal.get(native_day, ()) if v.security_id == sid]
        need(digest(asdict(native)) == case['native_term_sha256']
             and not native.completeness(0)[0], 'REMAINDER_ACTUAL_INCOMPLETE_NATIVE_PREIMAGE')
        natives[sid] = native
        for day in {case['core_session'], case['sensor_session']} - {native_day}:
            need(not [v for v in actions.terminal.get(day, ()) if v.security_id == sid],
                 'REMAINDER_NO_UNDECLARED_EFFECTIVE_DAY_COLLISION')
        need(case['core_session'] in dates and case['sensor_session'] in dates
             and native_day > cp['source_cursor'], 'REMAINDER_FROZEN_UNCONSUMED_DATE_AXIS')
        last = case['primary_facts']['true_last_trading'] or '2026-07-23'
        for day in {native_day, last, case['sensor_session']}:
            keys[day, sid] = None
    keys['2025-05-19', '326864109633904206'] = None
    annual = []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for item in catalog['full_source_members']:
            name = item['name']; info = archive.getinfo(name)
            need(info.file_size == item['bytes'] and info.CRC == item['crc32'],
                 'REMAINDER_FROZEN_YEAR_MEMBER_SIZE_AND_CRC')
            with archive.open(name) as source:
                import hashlib
                h = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    h.update(chunk)
            need(h.hexdigest() == item['sha256'], 'REMAINDER_FROZEN_YEAR_ACTUAL_HASH')
            count = 0
            for row in inputs._archive_rows(archive, name):
                count += 1; key = row['session'], row['security_id']
                if key in keys:
                    need(keys[key] is None, 'REMAINDER_UNIQUE_ACTUAL_SOURCE_QUOTE')
                    keys[key] = dict(row)
            need(count == item['all_rows'], 'REMAINDER_COMPLETE_ANNUAL_RAW_AXIS')
            annual.append(dict(item, actual_rows=count))
    quotes, last_witnesses = {}, {}
    for case in catalog['cases']:
        sid = case['security_id']; row = keys[case['sensor_session'], sid]
        expect = case['event_quote']
        need((row is not None) == expect['present'] and (row is None or digest(row) == expect['row_sha256']),
             'REMAINDER_ACTUAL_EVENT_QUOTE_PREIMAGE_OR_PROVEN_ABSENCE')
        quotes[case['ticker']] = dict(expect, session=case['sensor_session'], security_id=sid, row=row)
        last = case['primary_facts']['true_last_trading'] or '2026-07-23'
        witness = keys[last, sid]
        need(witness is not None and witness['ticker'] == case['ticker'],
             'REMAINDER_ACTUAL_LAST_TRADE_IDENTITY_WITNESS')
        last_witnesses[case['ticker']] = witness
    delivered = keys['2025-05-19', '326864109633904206']
    need(delivered is not None and delivered['ticker'] == 'COF'
         and delivered['issuer_id'] == 'SEC_CIK:927628', 'REMAINDER_DFS_ACTUAL_DELIVERED_QUOTE_IDENTITY')
    raw = (Path(old) / 'provider-source/SHARADAR_ACTIONS.zip').read_bytes()
    need(len(raw) == catalog['provider_bytes'] and sha(raw) == catalog['provider_sha256'],
         'REMAINDER_EXACT_ORIGINAL_FULL_PROVIDER_ARCHIVE')
    provider = {v['ticker']: [] for v in catalog['cases']}; count = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf8', newline='')):
                    count += 1
                    for case in catalog['cases']:
                        if row['date'] == case['native_session'] and case['ticker'] in (row['ticker'], row['contraticker']):
                            provider[case['ticker']].append(dict(row))
    need(count == catalog['provider_all_rows'] and all(provider.values()),
         'REMAINDER_EVERY_PHYSICAL_PROVIDER_ROW_AND_SEVEN_SOURCE_ROLES')
    payload = dict(schema='research.p02-remainder-terminal-private/1', catalog=catalog,
        natives={sid: asdict(v) for sid, v in natives.items()}, annual=annual,
        event_quotes=quotes, last_witnesses=last_witnesses, delivered_quote=delivered,
        physical_provider_rows=provider, all_provider_rows=count,
        raw_preimages_retained=True, source_quote_or_eligibility_edits=False)
    save(Path(out) / PRIVATE, payload)
    return SimpleNamespace(catalog=catalog, payload=payload, natives=natives)


def evidence(root):
    root = Path(root)
    entries = [('catalog', Path(__file__).parent / CATALOG), ('private', root / PRIVATE),
        ('ordinary-overlay', root / ORDINARY), ('input-parser', Path(__file__).with_name('system_campaign_remainder_input.py')),
        ('factual-hydration', Path(__file__)), ('sensor-adapter', Path(__file__).with_name('system_campaign_remainder_sensor.py')),
        ('canonical-gate', Path(__file__).with_name('system_campaign_remainder_gate.py')),
        ('independent-review', Path(__file__).with_name('system_campaign_remainder_review.py'))]
    return [dict(reference='research:system-optimization-002/remainder-terminals/1/' + kind,
        sha256=sha(path.read_bytes()), description='Exact own-bound factual input and isolated sensor proof implementation.')
        for kind, path in entries]


def prepare(cp, old, out, spec):
    from system_campaign_remainder_input import parent_binding
    facts = hydrate(cp, old, out)
    terms = [v for v in facts.catalog['cases'] if v['treatment'] != 'CVR_RANGE']
    patch = dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=[dict(reference=url, sha256=None, description=v['primary_facts']['source_discrepancy'])
                         for v in terms for url in v['primary_facts']['sources']],
        suppress=[dict(session=v['native_session'], security_id=v['security_id'],
                       term_sha256=v['native_term_sha256']) for v in terms], add=[v['added'] for v in terms])
    save(Path(out) / ORDINARY, patch)
    raw = (Path(old) / spec['selected_checkpoint']).read_bytes()
    parent = parent_binding(cp, raw, spec['selected_file']['sha256'])
    refs = evidence(out)
    value = dict(schema=SCHEMA, predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        parent=parent, catalog_sha256=digest(facts.catalog), private_sha256=sha((Path(out) / PRIVATE).read_bytes()),
        ordinary_overlay_sha256=sha((Path(out) / ORDINARY).read_bytes()),
        treatment='CANONICAL_ACTIONS_AND_UNOWNED_COMPLETE_OUTCOME_RANGE_PROOF', source_evidence=refs)
    path = Path(out) / 'remainder-terminal-input.json'; save(path, value)
    return facts, parent, refs, path
