"""Original SONC cash fact on this experiment's own reviewed predecessor."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from core_volatility_source import need, sha
from full_system_core import hosted
from full_system_benchmark import save

SID = '789689535963205828'
PARENT = '0c98e3a7487b79646d6f1275fc7bafbe5d0e91045ab6740bd6da5895456c48d6'
CATALOG = 'system-campaign-additional-terminal-facts.json'
CATALOG_SHA = '727c506bfb52ea730ba32fb97faaec4ab2d73819d3b8068ec1162d4e446d7449'
SCOPE = 'core-volatility-sonc-source-scope.json'
REFERENCE = 'research:core-volatility-20261108/original-sonc-completion-facts/1'


def own_scope(cp, arm):
    need(arm == 'VOL075' and cp['sha256'] == PARENT and cp['completed'] == 232
         and cp['source_cursor'] == '2018-11-30', 'EXACT_SONC_OWN_COMMITTED_PREDECESSOR')
    state = cp['run']['state']
    selected = [e for e in state['wealth_core']['episodes'].values() if e['security_id'] == SID]
    need(len(selected) == 1 and selected[0]['current_shares'] == selected[0]['initial_shares'] == 63
         and selected[0]['entry_date'] == '2018-11-27' and selected[0]['signal_date'] == '2018-11-26'
         and selected[0]['slot_id'] == 1 and selected[0]['ticker'] == 'SONC'
         and not selected[0]['exit_pending']
         and not any(p.get('security_id') == SID for p in state['pending']),
         'OWN_63_SHARE_SONC_WITHOUT_FOREIGN_POSITIONS')


def selected_term(raw):
    need(sha(raw) == CATALOG_SHA, 'EXACT_ORIGINAL_SONC_FACT_CATALOG')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.system-campaign-additional-terminal-facts/1'
         and not catalog['canonical_financial_source_changed'] and not catalog['production_contacted'],
         'ORIGINAL_SONC_COMPLETION_INPUT_SCOPE')
    term, = [deepcopy(t) for t in catalog['terms'] if t['security_id'] == SID]
    need(term['ticker'] == 'SONC' and term['native_session'] == '2018-12-07'
         and term['native_term_sha256'] == '5f13089ea020fe7fa5eb2aa6f72aa82a64943e4d45ed6eff6a29d4d74a8cc64d'
         and term['added']['session'] == '2018-12-07' and term['added']['kind'] == 'CASH_MERGER'
         and term['added']['cash_per_share'] == 43.5 and term['proxy'] is None,
         'EXACT_PUBLISHED_SONC_CASH_TERMS')
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
    need(scope['security_id'] == SID and scope['actual_completion_date'] == '2018-12-07'
         and not scope['provider_metadata_upgraded'], 'DECLARED_SONC_PRIMARY_COMPLETION_DATE')
    need('2018-12-07' in axis(), 'EXACT_SONC_COMPLETION_MARKET_SESSION')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native, = [v for v in actions.terminal.get(term['native_session'], ()) if v.security_id == SID]
    need(original.digest(asdict(native)) == term['native_term_sha256'] and not native.completeness(0)[0],
         'EXACT_FROZEN_INCOMPLETE_SONC_NATIVE')
    wanted = {(w['session'], w['security_id']): w for w in scope['witnesses']}
    need(set(wanted) == {(d, SID) for d in ('2018-11-26', '2018-11-27', '2018-12-06')}, 'EXACT_SONC_SOURCE_WITNESS_DATES')
    seen = set()
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2018.csv.gz'):
            key = row['session'], row['security_id']
            if key in wanted:
                need(key not in seen, 'UNIQUE_SONC_SOURCE_ROW')
                require_witness(row, wanted[key])
                need(row['issuer_id'] == 'SEC_CIK:868611' and row['security_type_eligible'] == '1',
                     'ORIGINAL_SONC_ISSUER_AND_ELIGIBILITY_PRESERVED')
                seen.add(key)
    need(seen == set(wanted), 'ALL_FROZEN_SONC_SOURCE_WITNESSES')
    term['identity_witness'] = wanted['2018-11-26', SID]
    term['last_trading_session'] = '2018-12-06'
    material = {'schema': REFERENCE, 'arm': arm, 'parent_outer_sha256': cp['sha256'], 'terms': [term],
                'original_book_authority_reused': False, 'provider_metadata_upgraded': False,
                'actual_exchange_agent_payment_time_claimed': False}
    hydrated = root/'own-sonc-input-facts.json'
    save(hydrated, material)
    document = {'schema': 'terminal-repair/1', 'predecessor_checkpoint_sha256': cp['run']['checkpoint_sha256'],
        'source_evidence': [dict(reference=REFERENCE, description=term['description'], sha256=sha(hydrated.read_bytes())),
            dict(reference=REFERENCE+'/original-catalog', description='Unchanged original completion input.', sha256=CATALOG_SHA),
            dict(reference=REFERENCE+'/source-scope', description='Exact frozen identity/row witnesses; original metadata retained.', sha256=sha((driver/SCOPE).read_bytes())),
            dict(reference=REFERENCE+'/compiler', description='Own-predecessor future-only SONC completion compiler.', sha256=sha(Path(__file__).read_bytes())),
            dict(reference=term['primary_source'], description=term['description'], sha256=None)],
        'suppress': original.suppressions(cp, [term]), 'add': [deepcopy(term['added'])]}
    overlay = root/'own-sonc-overlay.json'
    save(overlay, document)
    loaded = load_repair(overlay, resume_session=cp['source_cursor'],
                         predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'sonc-input-qualification'
    audit.mkdir()
    original.qualify(cp, material, {}, actions, loaded, overlay, audit)
    return ['--repair-overlay', str(overlay)], material


def observer(root, cp, material):
    hosted()
    own_scope(cp, material['arm'])
    from system_campaign_financial_future import ActualEvents
    term, = material['terms']
    need(term['added']['kind'] == 'CASH_MERGER' and term['added']['cash_per_share'] == 43.5
         and term['security_id'] == SID and material['parent_outer_sha256'] == cp['sha256']
         and not material['provider_metadata_upgraded'], 'ACTUAL_SONC_COMPLETION_SCOPE')
    class OwnCompletionEvents(ActualEvents):
        def __init__(self):
            self.out, self.arm = root, material['arm']
            self.terms = {(term['added']['session'], SID): deepcopy(term['added'])}
            self.scopes = []
            self.saved, self.current = [], None
    return OwnCompletionEvents()
