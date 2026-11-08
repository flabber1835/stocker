"""Original SODA cash facts; new own predecessor, original provider metadata."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from core_volatility_source import need, sha
from full_system_core import hosted
from full_system_benchmark import save

SID = '580777104042893954'
PARENT = 'a18d150fc7136881a641b66fba9a6a52f6b614cdf0b6c298ee67a8a7066d3a52'
CATALOG = 'system-campaign-additional-terminal-facts.json'
CATALOG_SHA = '727c506bfb52ea730ba32fb97faaec4ab2d73819d3b8068ec1162d4e446d7449'
SCOPE = 'core-volatility-soda-source-scope.json'
REFERENCE = 'research:core-volatility-20261108/original-soda-completion-facts/1'


def own_scope(cp, arm):
    need(arm == 'VOL075' and cp['sha256'] == PARENT and cp['completed'] == 232
         and cp['source_cursor'] == '2018-11-30', 'EXACT_SODA_OWN_COMMITTED_PREDECESSOR')
    state = cp['run']['state']
    selected = [v for v in state['pending'] if v.get('security_id') == SID]
    need(len(selected) == 1 and selected[0]['operation'] == 'OPEN_SLOT_POSITION'
         and selected[0]['signal_session'] == '2018-11-30' and selected[0]['slot_id'] == 8
         and selected[0]['ticker'] == 'SODA'
         and not any(e['security_id'] == SID for e in state['wealth_core']['episodes'].values()),
         'OWN_PENDING_SODA_WITHOUT_FOREIGN_POSITIONS')


def selected_term(raw):
    need(sha(raw) == CATALOG_SHA, 'EXACT_ORIGINAL_SODA_FACT_CATALOG')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.system-campaign-additional-terminal-facts/1'
         and not catalog['canonical_financial_source_changed'] and not catalog['production_contacted'],
         'ORIGINAL_COMPLETION_INPUT_SCOPE')
    term, = [deepcopy(t) for t in catalog['terms'] if t['security_id'] == SID]
    need(term['ticker'] == 'SODA' and term['native_session'] == '2018-12-04'
         and term['added']['session'] == '2018-12-06' and term['added']['kind'] == 'CASH_MERGER'
         and term['added']['cash_per_share'] == 144. and term['proxy'] is None, 'EXACT_PUBLISHED_SODA_CASH_TERMS')
    return term


def prepare(cp, root, arm):
    hosted()
    own_scope(cp, arm)
    import system_campaign_financial_future as original
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding.repair import load_repair
    from system_campaign_2021_completions_facts import require_witness
    driver = Path('/driver')
    term = selected_term((driver/CATALOG).read_bytes())
    scope = json.loads((driver/SCOPE).read_bytes())
    need(scope['security_id'] == SID and scope['actual_completion_date'] == '2018-12-05', 'DECLARED_PRIMARY_COMPLETION_DATE')
    dates = axis()
    need('2018-12-05' not in dates and next(day for day in dates if day > '2018-12-05') == '2018-12-06',
         'EXACT_FIRST_FROZEN_SESSION_AFTER_COMPLETION')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native, = [v for v in actions.terminal.get(term['native_session'], ()) if v.security_id == SID]
    need(original.digest(asdict(native)) == term['native_term_sha256'] and not native.completeness(0)[0],
         'EXACT_FROZEN_INCOMPLETE_SODA_NATIVE')
    need(not [v for v in actions.terminal.get('2018-12-06', ()) if v.security_id == SID], 'NO_CONFLICTING_COMPLETION_TERM')
    wanted = {(w['session'], w['security_id']): w for w in scope['witnesses']}
    need(set(wanted) == {(d, SID) for d in ('2018-11-30', '2018-12-03', '2018-12-04')}, 'EXACT_SOURCE_WITNESS_DATES')
    seen = set()
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2018.csv.gz'):
            key = row['session'], row['security_id']
            if key in wanted:
                need(key not in seen, 'UNIQUE_SODA_SOURCE_ROW')
                require_witness(row, wanted[key])
                need(row['issuer_id'] == 'SEC_UNKNOWN:'+SID and row['security_type_eligible'] == '0',
                     'ORIGINAL_UNKNOWN_ISSUER_AND_ELIGIBILITY_NOT_UPGRADED')
                seen.add(key)
    need(seen == set(wanted), 'ALL_FROZEN_SODA_SOURCE_WITNESSES')
    term['identity_witness'] = wanted['2018-11-30', SID]
    term['last_trading_session'] = '2018-12-04'
    material = {'schema': REFERENCE, 'arm': arm, 'parent_outer_sha256': cp['sha256'], 'terms': [term],
                'original_book_authority_reused': False, 'provider_metadata_upgraded': False,
                'actual_exchange_agent_payment_time_claimed': False}
    hydrated = root/'own-completion-input-facts.json'
    save(hydrated, material)
    document = {'schema': 'terminal-repair/1', 'predecessor_checkpoint_sha256': cp['run']['checkpoint_sha256'],
        'source_evidence': [dict(reference=REFERENCE, description=term['description'], sha256=sha(hydrated.read_bytes())),
            dict(reference=REFERENCE+'/original-catalog', description='Unchanged original completion input.', sha256=CATALOG_SHA),
            dict(reference=REFERENCE+'/source-scope', description='Exact frozen identity/row witnesses; original unknown issuer and eligibility retained.', sha256=sha((driver/SCOPE).read_bytes())),
            dict(reference=REFERENCE+'/compiler', description='Own-predecessor future-only completion compiler.', sha256=sha(Path(__file__).read_bytes())),
            dict(reference=term['primary_source'], description=term['description'], sha256=None)],
        'suppress': original.suppressions(cp, [term]), 'add': [deepcopy(term['added'])]}
    overlay = root/'own-completion-overlay.json'
    save(overlay, document)
    loaded = load_repair(overlay, resume_session=cp['source_cursor'],
                         predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'completion-input-qualification'
    audit.mkdir()
    original.qualify(cp, material, {}, actions, loaded, overlay, audit)
    return ['--repair-overlay', str(overlay)], material


def observer(root, cp, material):
    hosted()
    own_scope(cp, material['arm'])
    from system_campaign_financial_future import ActualEvents
    term, = material['terms']
    need(term['added']['kind'] == 'CASH_MERGER' and term['added']['cash_per_share'] == 144.
         and term['security_id'] == SID and material['parent_outer_sha256'] == cp['sha256']
         and not material['provider_metadata_upgraded'], 'ACTUAL_SODA_COMPLETION_SCOPE')
    class OwnCompletionEvents(ActualEvents):
        def __init__(self):
            self.out, self.arm = root, material['arm']
            self.terms = {(term['added']['session'], SID): deepcopy(term['added'])}
            self.scopes = []
            self.saved, self.current = [], None
    return OwnCompletionEvents()
