"""Original qualified GBT ordinary cash on the alternative's own 75 shares."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from core_volatility_source import need, sha
from core_volatility_admit import digest
from full_system_core import hosted
from full_system_benchmark import save

SID = '827416728546053456'
PARENT = '376b422e09e8cf01c682b674dfee80d5ff483c0b4a7fab6ddbf78472642b84af'
CATALOG = 'system-campaign-selected-own-cash-terminal-facts.json'
CATALOG_SHA = '9ef287a863e6fc5e6e0754ed8fe052b9fdc40a1353a68bf5e55e4398f03558b5'
TERM_SHA = 'df05ef7fe246b136cd9b143e25645b37df0420c583f8f617fa65993aa51bd384'
SCOPE = 'core-volatility-gbt-source-scope.json'
REFERENCE = 'research:core-volatility-20261108/original-gbt-cash-facts/1'


def own_scope(cp, arm):
    need(arm == 'VOL075' and cp['sha256'] == PARENT and cp['completed'] == 1196
         and cp['source_cursor'] == '2022-09-30', 'EXACT_GBT_OWN_COMMITTED_PREDECESSOR')
    state = cp['run']['state']
    selected = [e for e in state['wealth_core']['episodes'].values() if e['security_id'] == SID]
    need(len(selected) == 1 and selected[0]['current_shares'] == selected[0]['initial_shares'] == 75
         and selected[0]['entry_date'] == '2022-09-12' and selected[0]['signal_date'] == '2022-09-09'
         and selected[0]['slot_id'] == 16 and selected[0]['ticker'] == 'GBT' and not selected[0]['exit_pending']
         and not any(p.get('security_id') == SID for p in state['pending']), 'OWN_75_ORDINARY_GBT_SHARES_NOT_FOREIGN_POSITIONS')


def selected_term(raw):
    need(sha(raw) == CATALOG_SHA, 'EXACT_ORIGINAL_GBT_CATALOG')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.selected-own-parent-completions/2'
         and not catalog['canonical_financial_source_changed'] and not catalog['production_contacted']
         and not catalog['provider_metadata_upgraded'], 'ORIGINAL_GBT_INPUT_SCOPE')
    term, = [deepcopy(t) for t in catalog['terms'] if t['security_id'] == SID]
    need(digest(term) == TERM_SHA and term['ticker'] == 'GBT' and term['native_session'] == '2022-10-04'
         and term['actual_completion_date'] == term['added']['session'] == '2022-10-05'
         and term['recognition_rule'] == 'CONFIRMED_PREOPEN_COMPLETION'
         and term['mandatory_common_share_completion_confirmed'] and term['preopen_completion_confirmed']
         and term['added']['kind'] == 'CASH_MERGER' and term['added']['cash_per_share'] == 68.5,
         'EXACT_PREEXISTING_GBT_ORDINARY_CASH_AND_CLOCK')
    return term


def source_scope(raw, term):
    scope = json.loads(raw)
    wanted = {(w['session'], w['security_id']): w for w in scope['witnesses']}
    need(scope['schema'] == 'research.core-volatility-gbt-source-scope/1'
         and scope['security_id'] == SID and not scope['provider_metadata_upgraded']
         and not scope['raw_prices_published'] and len(scope['witnesses']) == 3
         and set(wanted) == {(d, SID) for d in ('2022-09-30', '2022-10-03', '2022-10-04')}
         and wanted['2022-10-03', SID] == term['identity_witness']
         and all(w['issuer_id'] == 'SEC_CIK:1629137' and w['security_type_eligible'] == '1'
                 and w['ticker'] == 'GBT' and w['listing_first_session'] == '2015-08-12'
                 for w in wanted.values()), 'EXACT_OWN_AND_ORIGINAL_GBT_SOURCE_WITNESSES')
    return wanted


def prepare(cp, root, arm):
    hosted()
    own_scope(cp, arm)
    import system_campaign_financial_future as original
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding.repair import load_repair
    from system_campaign_2021_completions_facts import require_witness
    codec, name, chosen = original.own_cash_selection('P04', '2022-09-30')
    term, = deepcopy(chosen)
    need(name == CATALOG and codec.catalog_sha == CATALOG_SHA
         and term == selected_term((Path('/driver')/CATALOG).read_bytes()), 'ORIGINAL_CLOSED_GBT_SOURCE_SELECTION')
    need(next(d for d in axis() if d > term['last_trading_session']) == term['added']['session'], 'GBT_FIRST_POST_TRADING_OPEN')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native, = [v for v in actions.terminal.get(term['native_session'], ()) if v.security_id == SID]
    need(original.digest(asdict(native)) == term['native_term_sha256'] and not native.completeness(0)[0], 'EXACT_INCOMPLETE_GBT_NATIVE')
    need(not [v for v in actions.terminal.get(term['added']['session'], ()) if v.security_id == SID], 'NO_CONFLICTING_GBT_TERM')
    wanted = source_scope((Path('/driver')/SCOPE).read_bytes(), term)
    seen = set()
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2022.csv.gz'):
            key = row['session'], row['security_id']
            if key in wanted:
                need(key not in seen, 'UNIQUE_GBT_SOURCE_ROW')
                require_witness(row, wanted[key])
                need(row['issuer_id'] == 'SEC_CIK:1629137' and row['security_type_eligible'] == '1', 'ORIGINAL_GBT_PROVIDER_METADATA_PRESERVED')
                seen.add(key)
    need(seen == set(wanted), 'ALL_GBT_SOURCE_WITNESSES')
    material = dict(schema=REFERENCE, arm=arm, parent_outer_sha256=cp['sha256'], terms=[term],
        original_book_authority_reused=False, actual_exchange_agent_payment_time_claimed=False, provider_metadata_upgraded=False)
    hydrated = root/'own-gbt-input-facts.json'
    save(hydrated, material)
    document = dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=[dict(reference=REFERENCE, description=term['description'], sha256=sha(hydrated.read_bytes())),
            dict(reference=REFERENCE+'/original-catalog', description='Unchanged qualified ordinary-cash input.', sha256=CATALOG_SHA),
            dict(reference=REFERENCE+'/source-scope', description='Exact frozen own/original identity witnesses.', sha256=sha((Path('/driver')/SCOPE).read_bytes())),
            dict(reference=REFERENCE+'/compiler', description='Own-predecessor GBT input compiler.', sha256=sha(Path(__file__).read_bytes())),
            dict(reference=REFERENCE+'/original-validator', description='Unchanged closed source selection and canonical qualification.', sha256=sha(Path(original.__file__).read_bytes())),
            dict(reference=term['primary_source'], description=term['description'], sha256=None),
            dict(reference=term['timing_source'], description='Exchange confirms preopen completion and October4 final trading.', sha256=None)],
        suppress=original.suppressions(cp, [term]), add=[deepcopy(term['added'])])
    overlay = root/'own-gbt-overlay.json'
    save(overlay, document)
    loaded = load_repair(overlay, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'gbt-input-qualification'
    audit.mkdir()
    original.qualify(cp, material, {}, actions, loaded, overlay, audit)
    return ['--repair-overlay', str(overlay)], material


def observer(root, cp, material):
    hosted()
    own_scope(cp, material['arm'])
    from system_campaign_financial_future import ActualEvents
    term, = material['terms']
    need(digest(term) == TERM_SHA and material['parent_outer_sha256'] == cp['sha256']
         and not material['original_book_authority_reused'] and not material['actual_exchange_agent_payment_time_claimed'], 'ACTUAL_OWN_GBT_CASH_SCOPE')
    class OwnGbtEvents(ActualEvents):
        def __init__(self):
            self.out, self.arm = root, material['arm']
            self.terms = {(term['added']['session'], SID): deepcopy(term['added'])}
            self.scopes = []
            self.saved, self.current = [], None
    return OwnGbtEvents()
