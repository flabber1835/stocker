"""Closed original cash catalog cases, each bound to its own reviewed parent."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from core_volatility_source import need, sha
from full_system_core import hosted
from full_system_benchmark import save

CATALOG = 'system-campaign-additional-terminal-facts.json'
CATALOG_SHA = '727c506bfb52ea730ba32fb97faaec4ab2d73819d3b8068ec1162d4e446d7449'
CASES = {'BEL': {
    'sid': '882904858327189489', 'parent': '7975a110809bef89073a71c6730bdf92ec87205ee53950d324d4f10fa71d60c7',
    'cursor': '2019-03-29', 'completed': 312, 'shares': 102, 'slot': 19,
    'entry': '2018-12-26', 'signal': '2018-12-24', 'native': '2019-04-16', 'effective': '2019-04-17',
    'native_sha': '63b847254ce2f74e3f9e3155130524826894c316a35bc3a60fe83ea1e244650a', 'cash': 25.,
    'last_trade': '2019-04-16', 'completion': '2019-04-17', 'witness_dates': ('2019-03-29', '2019-04-16'),
    'scope': 'core-volatility-bel-source-scope.json', 'member': 'observations-2019.csv.gz',
    'issuer': 'SEC_UNKNOWN:882904858327189489', 'eligible': '0',
}}


def own_scope(cp, arm, name):
    case = CASES[name]
    need(arm == 'VOL075' and cp['sha256'] == case['parent'] and cp['completed'] == case['completed']
         and cp['source_cursor'] == case['cursor'], 'EXACT_CASH_CASE_OWN_COMMITTED_PREDECESSOR')
    state = cp['run']['state']
    selected = [e for e in state['wealth_core']['episodes'].values() if e['security_id'] == case['sid']]
    need(len(selected) == 1 and selected[0]['current_shares'] == selected[0]['initial_shares'] == case['shares']
         and selected[0]['entry_date'] == case['entry'] and selected[0]['signal_date'] == case['signal']
         and selected[0]['slot_id'] == case['slot'] and selected[0]['ticker'] == name and not selected[0]['exit_pending']
         and not any(p.get('security_id') == case['sid'] for p in state['pending']), 'EXACT_OWN_CASH_CASE_POSITION')


def selected_term(raw, name):
    case = CASES[name]
    need(sha(raw) == CATALOG_SHA, 'EXACT_ORIGINAL_CLOSED_CASH_CATALOG')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.system-campaign-additional-terminal-facts/1'
         and not catalog['canonical_financial_source_changed'] and not catalog['production_contacted'], 'CLOSED_CASH_CATALOG_SCOPE')
    term, = [deepcopy(t) for t in catalog['terms'] if t['security_id'] == case['sid']]
    need(term['ticker'] == name and term['native_session'] == case['native'] and term['native_term_sha256'] == case['native_sha']
         and term['added']['session'] == case['effective'] and term['added']['kind'] == 'CASH_MERGER'
         and term['added']['cash_per_share'] == case['cash'] and term['proxy'] is None, 'EXACT_CLOSED_CASH_TERMS')
    return term


def prepare(cp, root, arm, name):
    hosted()
    own_scope(cp, arm, name)
    case = CASES[name]
    sid = case['sid']
    reference = 'research:core-volatility-20261108/original-cash-facts/'+name+'/1'
    import system_campaign_financial_future as original
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding.repair import load_repair
    from system_campaign_2021_completions_facts import require_witness
    driver = Path('/driver')
    term = selected_term((driver/CATALOG).read_bytes(), name)
    scope = json.loads((driver/case['scope']).read_bytes())
    need(scope['security_id'] == sid and scope['actual_completion_date'] == case['completion']
         and scope['primary_source'] == term['primary_source'] and not scope['provider_metadata_upgraded'], 'CLOSED_CASH_PRIMARY_DATE_AND_SCOPE')
    dates = axis()
    need(case['effective'] in dates and next(d for d in dates if d > case['last_trade']) == case['effective'], 'CLOSED_CASH_FIRST_NONTRADING_OPEN')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native, = [v for v in actions.terminal.get(case['native'], ()) if v.security_id == sid]
    need(original.digest(asdict(native)) == case['native_sha'] and not native.completeness(0)[0], 'EXACT_CLOSED_CASH_INCOMPLETE_NATIVE')
    need(not [v for v in actions.terminal.get(case['effective'], ()) if v.security_id == sid], 'NO_CONFLICTING_CLOSED_CASH_TERM')
    wanted = {(w['session'], w['security_id']): w for w in scope['witnesses']}
    need(set(wanted) == {(d, sid) for d in case['witness_dates']}, 'EXACT_CLOSED_CASH_SOURCE_DATES')
    seen = set()
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, case['member']):
            key = row['session'], row['security_id']
            if key in wanted:
                need(key not in seen, 'UNIQUE_CLOSED_CASH_SOURCE_ROW')
                require_witness(row, wanted[key])
                need(row['issuer_id'] == case['issuer'] and row['security_type_eligible'] == case['eligible'], 'CLOSED_CASH_PROVIDER_METADATA_PRESERVED')
                seen.add(key)
    need(seen == set(wanted), 'ALL_CLOSED_CASH_SOURCE_WITNESSES')
    term['identity_witness'] = wanted[case['cursor'], sid]
    term['last_trading_session'] = case['last_trade']
    material = {'schema': reference, 'arm': arm, 'name': name, 'parent_outer_sha256': cp['sha256'], 'terms': [term],
                'original_book_authority_reused': False, 'provider_metadata_upgraded': False,
                'actual_exchange_agent_payment_time_claimed': False}
    hydrated = root/'own-cash-input-facts.json'
    save(hydrated, material)
    document = {'schema': 'terminal-repair/1', 'predecessor_checkpoint_sha256': cp['run']['checkpoint_sha256'],
        'source_evidence': [dict(reference=reference, description=term['description'], sha256=sha(hydrated.read_bytes())),
            dict(reference=reference+'/original-catalog', description='Unchanged original cash input.', sha256=CATALOG_SHA),
            dict(reference=reference+'/source-scope', description='Exact frozen identity/witnesses; original metadata retained.', sha256=sha((driver/case['scope']).read_bytes())),
            dict(reference=reference+'/compiler', description='Closed own-predecessor future-only cash compiler.', sha256=sha(Path(__file__).read_bytes())),
            dict(reference=term['primary_source'], description=term['description'], sha256=None)],
        'suppress': original.suppressions(cp, [term]), 'add': [deepcopy(term['added'])]}
    overlay = root/'own-cash-overlay.json'
    save(overlay, document)
    loaded = load_repair(overlay, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'cash-input-qualification'
    audit.mkdir()
    original.qualify(cp, material, {}, actions, loaded, overlay, audit)
    return ['--repair-overlay', str(overlay)], material


def observer(root, cp, material):
    hosted()
    name = material['name']
    own_scope(cp, material['arm'], name)
    case = CASES[name]
    from system_campaign_financial_future import ActualEvents
    term, = material['terms']
    need(term['added']['kind'] == 'CASH_MERGER' and term['added']['cash_per_share'] == case['cash']
         and term['security_id'] == case['sid'] and material['parent_outer_sha256'] == cp['sha256']
         and not material['provider_metadata_upgraded'], 'ACTUAL_CLOSED_CASH_COMPLETION_SCOPE')
    class OwnCashEvents(ActualEvents):
        def __init__(self):
            self.out, self.arm = root, material['arm']
            self.terms = {(term['added']['session'], case['sid']): deepcopy(term['added'])}
            self.scopes = []
            self.saved, self.current = [], None
    return OwnCashEvents()
