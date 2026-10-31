"""Hosted frozen-source admission for the October batch's guarded envelope."""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import zipfile

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_cash_calendar import CashCalendar, build as build_cash
from system_campaign_completion_scope import SCHEMA, SCOPE, NATIVES, COMPLETIONS, digest, parse
from system_campaign_facts import sha


HERE = Path(__file__).resolve().parent
CONTRACT = 'system-campaign-completion-scope-contract.json'
CATALOG = 'system-campaign-october-cash-calendar-terminal-facts.json'
PRIVATE = 'hydrated-completion-scope-events.json'
OVERLAY = 'october-guarded-completion-input.json'
IMPLEMENTATIONS = ('system_campaign_completion_scope.py', 'system_campaign_completion_facts.py',
                   'system_campaign_completion_basis.py', 'system_campaign_completion_gate.py',
                   'system_campaign_completion_review.py')


def contract():
    c = json.loads((HERE / CONTRACT).read_bytes())
    need(c['schema'] == 'research.guarded-completion-contract/1' and c['scope'] == SCOPE
         and c['ordinary_catalog'] == CATALOG
         and c['ordinary_catalog_sha256'] == sha((HERE / CATALOG).read_bytes())
         and not c['canonical_financial_source_changed'] and not c['provider_metadata_upgraded']
         and not c['production_contacted'], 'COMPLETION_EXACT_PUBLIC_CONTRACT')
    need({e['security_id']: e['native_session'] for e in c['scoped_events']} == NATIVES
         and {e['security_id']: e['session'] for e in c['scoped_events']} == COMPLETIONS,
         'COMPLETION_ONLY_TWO_DECLARED_SCOPED_NAMES')
    for event in c['scoped_events']:
        need(event['mandatory_remaining_common_share_entitlement'] is True
             and event['preopen_completion_claimed'] is False
             and event['event_source_quote_present'] is False
             and datetime.fromisoformat(event['filing_accepted_utc'])
                 < datetime.fromisoformat(event['following_open_new_york']),
             'COMPLETION_MANDATORY_TERMS_BEFORE_FOLLOWING_EXECUTION')
    for name, expected in c['inherited_sources'].items():
        need(sha((HERE / name).read_bytes()) == expected, 'COMPLETION_INHERITED_IMPLEMENTATION_BYTES')
    return c


def evidence(root):
    names = (CONTRACT, *IMPLEMENTATIONS)
    rows = [dict(reference='research:system-optimization-002/completion-scope/' + name,
                 sha256=sha((HERE / name).read_bytes()),
                 description='Exact guarded completion contract or implementation.') for name in names]
    rows.append(dict(reference='research:system-optimization-002/completion-scope/private/1',
                     sha256=sha((root / PRIVATE).read_bytes()),
                     description='Actual full source rows, native terms and preserved complete COWN term.'))
    return rows


def ordinary_document(root, predecessor):
    """Reassemble the registered ordinary component without trusting its file."""
    catalog = json.loads((HERE / CATALOG).read_bytes())
    cash = CashCalendar(catalog)
    group = catalog['commitment_group']
    payload = json.loads((root / group['private_file']).read_bytes())
    need(payload['catalog'] == catalog, 'COMPLETION_ORDINARY_PRIVATE_CATALOG_BINDING')
    references = {'catalog': sha((HERE / CATALOG).read_bytes()),
                  'loader': sha((HERE / group['loader_file']).read_bytes()),
                  'private': sha((root / group['private_file']).read_bytes())}
    refs = [dict(reference=group['reference_stem'] + key, sha256=value,
                 description='Exact data-driven primary cash recognition calendar and frozen source witnesses.')
            for key, value in references.items()]
    for event in catalog['terms']:
        refs.extend(dict(reference=event[key], sha256=None, description=event['description'])
                    for key in ('primary_source', 'timing_source'))
    value = dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=predecessor,
                 source_evidence=refs, **cash.patch())
    need(json.loads((root / group['overlay_file']).read_bytes()) == value,
         'COMPLETION_EXACT_REASSEMBLED_ORDINARY_COMPONENT')
    return value


def expected_repair(root, predecessor):
    c = contract()
    value = ordinary_document(root, predecessor)
    for event in c['scoped_events']:
        value['suppress'].append(dict(session=event['native_session'], security_id=event['security_id'],
                                      term_sha256=event['native_term_sha256']))
        value['add'].append(event['added'])
    stale = c['suppression_only']
    value['suppress'].append(dict(session=stale['native']['session'],
                                  security_id=stale['native']['security_id'],
                                  term_sha256=stale['native_term_sha256']))
    value['source_evidence'].extend(evidence(root))
    for key in ('suppress', 'add'):
        rows = value[key]
        need(len({(t['session'], t['security_id']) for t in rows}) == len(rows),
             'COMPLETION_NO_DUPLICATE_NATIVE_OR_EFFECTIVE_IDENTITY')
    need(len(value['suppress']) == 20 and len(value['add']) == 19,
         'COMPLETION_EXACT_17_ORDINARY_TWO_SCOPED_ONE_SUPPRESSION_ONLY')
    return value


def hydrate(root, out):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    c = contract(); dates = axis(); actions = inputs.load_actions(Path('/frozen/bundle'))
    native = []; wanted = {}; found = {}; event_rows = []
    for event in c['scoped_events']:
        sid = event['security_id']; first = event['native_session']; day = event['session']
        need(dates[dates.index(first) + 1] == day, 'COMPLETION_ADJACENT_ACTUAL_PRICE_BASIS')
        need(datetime.fromisoformat(event['following_open_new_york']).date().isoformat()
             == dates[dates.index(day) + 1], 'COMPLETION_EXACT_FOLLOWING_TRADING_OPEN')
        terms = [t for t in actions.terminal.get(first, ()) if t.security_id == sid]
        need(len(terms) == 1 and asdict(terms[0]) == event['native']
             and digest(asdict(terms[0])) == event['native_term_sha256']
             and not terms[0].completeness(0)[0], 'COMPLETION_ACTUAL_INCOMPLETE_NATIVE')
        need(not any(t.security_id == sid for t in actions.terminal.get(day, ())),
             'COMPLETION_NO_UNDECLARED_EFFECTIVE_TERM_COLLISION')
        wanted[(first, sid)] = event['source_witness']; native.append(asdict(terms[0]))
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2022.csv.gz'):
            key = row['session'], row['security_id']
            if key in wanted:
                witness = wanted[key]
                need(key not in found and digest(row) == witness['source_observation_sha256']
                     and all(row[k] == v for k, v in witness.items() if k != 'source_observation_sha256'),
                     'COMPLETION_FULL_FROZEN_SOURCE_WITNESS')
                found[key] = row
            if any(row['session'] == e['session'] and row['security_id'] == e['security_id']
                   for e in c['scoped_events']):
                event_rows.append(row)
    need(set(found) == set(wanted) and not event_rows, 'COMPLETION_SOURCE_ROWS_AND_EFFECTIVE_QUOTE_ABSENCE')
    stale = c['suppression_only']; actual = []
    for expected in (stale['native'], stale['preserved_complete']):
        terms = [t for t in actions.terminal.get(expected['session'], ())
                 if t.security_id == expected['security_id']]
        need(len(terms) == 1 and asdict(terms[0]) == expected, 'COMPLETION_COWN_EXACT_BASE_PAIR')
        actual.append(asdict(terms[0]))
    need(digest(actual[0]) == stale['native_term_sha256']
         and digest(actual[1]) == stale['preserved_complete_sha256'], 'COMPLETION_COWN_EXACT_PAIR_HASHES')
    value = dict(schema='research.completion-scope-private-events/1', contract=c, native_terms=native,
                 source_witnesses=[found[k] for k in sorted(found)], effective_source_quotes=[],
                 cown_original_pair=actual, source_metadata_unchanged=True, production_contacted=False)
    save(out / PRIVATE, value)
    return value


def build(cp, old, out):
    hosted()
    cash, _, _ = build_cash(cp, old, out, HERE / CATALOG)
    hydrate(old, out)
    predecessor = cp['run']['checkpoint_sha256']
    body = expected_repair(out, predecessor)
    value = dict(schema=SCHEMA, predecessor_checkpoint_sha256=predecessor, scope=SCOPE,
                 require_unowned_and_unordered=True, morning_settlement_claimed=False,
                 canonical_repair=body, source_evidence=evidence(out))
    save(out / OVERLAY, value)
    obj = parse(out / OVERLAY, resume_session=cp['source_cursor'],
                predecessor_checkpoint_sha256=predecessor, expected_repair=body,
                expected_evidence=evidence(out))
    return cash, obj, out / OVERLAY
