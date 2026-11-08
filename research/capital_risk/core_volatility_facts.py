"""Reuse original P00 future factual inputs on each experiment's OWN book."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from core_volatility_source import need, sha
from full_system_core import hosted
from full_system_benchmark import save

REFERENCE = 'research:core-volatility-20261108/shared-original-p00-future-facts/1'
PHASES = (('P00', '2018-08-31', 'ILG'), ('P00', '2025-06-30', 'TGI'))


def document(cp, terms, evidence):
    need({t['ticker'] for t in terms} == {'ILG', 'TGI'} and len(terms) == 2, 'ORIGINAL_TWO_P00_FUTURE_FACTS')
    need(all(t['native_session'] > cp['source_cursor'] and t['added']['session'] > cp['source_cursor']
             for t in terms), 'UNCONSUMED_OWN_FUTURE_FACTS')
    return {'schema': 'terminal-repair/1', 'predecessor_checkpoint_sha256': cp['run']['checkpoint_sha256'],
            'source_evidence': evidence,
            'suppress': [{'session': t['native_session'], 'security_id': t['security_id'],
                          'term_sha256': t['native_term_sha256']} for t in terms],
            'add': [deepcopy(t['added']) for t in terms]}


def prepare(cp, root):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_vacancy_funding.repair import load_repair
    from system_campaign_2021_completions_facts import require_witness
    import system_campaign_financial_future as original
    # A later segment keeps this exact original document; never rebind a consumed
    # term to a different predecessor, and never borrow the other arm's book.
    retained = []
    for entry in cp['repairs']:
        raw = json.loads((root/'book/repairs'/entry['filename']).read_bytes())
        if any(e['reference'] == REFERENCE for e in raw['source_evidence']):
            retained.append(entry)
    if retained:
        need(len(retained) == 1, 'ONE_RETAINED_COMMON_FACT_DOCUMENT')
        return []
    need(cp['completed'] == 8 and cp['source_cursor'] == '2018-01-11', 'OWN_PAIRED_PILOT_FACT_PREDECESSOR')
    terms = []
    for arm, cursor, ticker in PHASES:
        codec, catalog, chosen = original.own_cash_selection(arm, cursor)
        need(len(chosen) == 1 and chosen[0]['ticker'] == ticker, 'ORIGINAL_LITERAL_FACT_SELECTION')
        terms.append(deepcopy(chosen[0]))
    actions = inputs.load_actions(Path('/frozen/bundle'))
    wanted = {}
    for t in terms:
        native, = [v for v in actions.terminal.get(t['native_session'], ()) if v.security_id == t['security_id']]
        need(original.digest(asdict(native)) == t['native_term_sha256'] == original.digest(t['native'])
             and not native.completeness(0)[0], 'EXACT_INCOMPLETE_NATIVE_PREIMAGE')
        need(not [v for v in actions.terminal.get(t['added']['session'], ()) if v.security_id == t['security_id']],
             'NO_CONFLICTING_EFFECTIVE_TERM')
        for witness in (t['identity_witness'], *([t['delivered_identity_witness']]
                                               if 'delivered_identity_witness' in t else [])):
            key = witness['session'], witness['security_id']
            need(key not in wanted, 'UNIQUE_ORIGINAL_WITNESS')
            wanted[key] = witness
    seen = {}
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, sid in wanted}):
            for row in inputs._archive_rows(archive, 'observations-'+year+'.csv.gz'):
                key = row['session'], row['security_id']
                if key in wanted:
                    need(key not in seen, 'UNIQUE_FROZEN_SOURCE_ROW')
                    require_witness(row, wanted[key])
                    seen[key] = row
    need(set(seen) == set(wanted), 'ALL_ORIGINAL_SOURCE_AND_DELIVERY_WITNESSES')
    delivered = {}
    for t in terms:
        if 'delivered_identity_witness' in t:
            w = t['delivered_identity_witness']
            row = seen[w['session'], w['security_id']]
            value = float(row['raw_open'])
            need(value > 0, 'ORIGINAL_POSITIVE_FRACTIONAL_RAW_OPEN_PROXY')
            t['added']['cash_in_lieu_price_per_delivered_share'] = value
            delivered[t['security_id']] = row
    material = {'schema': REFERENCE, 'parent_outer_sha256': cp['sha256'], 'terms': terms,
                'original_book_authority_reused': False, 'future_witnesses_verified': len(seen),
                'same_factual_and_fractional_proxy_basis_in_both_arms': True}
    hydrated = root/'shared-original-p00-future-facts.json'
    save(hydrated, material)
    evidence = [dict(reference=REFERENCE, description='Original P00 ILG/TGI facts, independently hydrated on this own predecessor; original book authority excluded.', sha256=sha(hydrated.read_bytes())),
                dict(reference=REFERENCE+'/compiler', description='Exact shared future-only input compiler.', sha256=sha(Path(__file__).read_bytes())),
                dict(reference=REFERENCE+'/original-validator', description='Unchanged original literal selection and canonical input qualifier.', sha256=sha(Path(original.__file__).read_bytes())),
                dict(reference=REFERENCE+'/original-catalog', description='Exact original primary-source/native catalog, unchanged clocks and fractional proxy.', sha256=original.OWN_CASH_SHA)]
    for t in terms:
        evidence.append(dict(reference=t['primary_source'], description=t['description'], sha256=None))
    path = root/'shared-original-p00-future-overlay.json'
    save(path, document(cp, terms, evidence))
    loaded = load_repair(path, resume_session=cp['source_cursor'],
                         predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'shared-future-qualification'
    audit.mkdir()
    original.qualify(cp, material, delivered, actions, loaded, path, audit)
    return ['--repair-overlay', str(path)]
