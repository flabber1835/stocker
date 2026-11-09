"""Qualify the prepared mandatory FMTX cash fact on this own future prefix."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from core_volatility_source import need, sha
from core_volatility_admit import digest
from full_system_core import hosted
from full_system_benchmark import save

SID = '321650252292096156'
PARENT = '15f55129e14c582e944f1f4341667be9b87dad78ae8f685fd3b5ee699cb8068d'
CATALOG = 'system-campaign-october-cash-calendar-terminal-facts.json'
CATALOG_SHA = '225b294cefd80c19b47090c24b246ac63456f6829dfe7816b41dfcdcfef2ad53'
TERM_SHA = '7cb6bf5a463628c7fdc39ff0f8092e90e3f88d1bfc9038cf470dabf5a90a6175'
LOADER_SHA = '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f'
REFERENCE = 'research:core-volatility-20261108/fmtx-own-future-qualification/1'


def own_scope(cp, arm):
    need(arm == 'VOL075' and cp['sha256'] == PARENT and cp['completed'] == 1196
         and cp['source_cursor'] == '2022-09-30', 'EXACT_FMTX_OWN_COMMITTED_PREDECESSOR')
    state = cp['run']['state']
    need(not any(e['security_id'] == SID for e in state['wealth_core']['episodes'].values())
         and not any(p.get('security_id') == SID for p in state['pending']), 'FMTX_OWN_UNHELD_UNORDERED_FUTURE_SCOPE')


def selected_term(raw):
    need(sha(raw) == CATALOG_SHA, 'EXACT_SOURCE_BOUND_OCTOBER_CATALOG')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.factual-cash-calendar-catalog/1'
         and catalog['preparation_status'] == 'SOURCE_BOUND_AWAITING_HOSTED_CANONICAL_QUALIFICATION'
         and catalog['loader_sha256'] == LOADER_SHA
         and all(catalog[k] is False for k in ('canonical_financial_source_changed', 'provider_metadata_upgraded', 'production_contacted')),
         'PREPARED_FMTX_NOT_PREVIOUSLY_ADOPTED')
    term, = [deepcopy(t) for t in catalog['terms'] if t['security_id'] == SID]
    need(digest(term) == TERM_SHA and term['ticker'] == 'FMTX'
         and term['added']['cash_per_share'] == 20. and term['added']['session'] == '2022-10-14'
         and term['native_session'] == term['last_trading_session'] == '2022-10-13'
         and term['recognition_rule'] == 'CONFIRMED_PREOPEN_COMPLETION'
         and term['timing_evidence']['input_adopted'] is False, 'EXACT_FMTX_MANDATORY_CASH_AND_CLOCK')
    return term


def prepare(cp, root, arm):
    hosted()
    own_scope(cp, arm)
    import system_campaign_cash_calendar as calendar
    import system_campaign_financial_future as original
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding.repair import load_repair
    from system_campaign_2021_completions_facts import require_witness
    need(sha(Path(calendar.__file__).read_bytes()) == LOADER_SHA, 'UNCHANGED_FMTX_CALENDAR_VALIDATOR')
    term = selected_term((Path('/driver')/CATALOG).read_bytes())
    calendar.validate_term(term)
    need(next(d for d in axis() if d > term['last_trading_session']) == term['added']['session'], 'FMTX_FIRST_POST_TRADING_OPEN')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native, = [v for v in actions.terminal.get(term['native_session'], ()) if v.security_id == SID]
    need(original.digest(asdict(native)) == term['native_term_sha256'] and not native.completeness(0)[0], 'EXACT_INCOMPLETE_FMTX_NATIVE')
    need(not [v for v in actions.terminal.get(term['added']['session'], ()) if v.security_id == SID], 'NO_CONFLICTING_FMTX_TERM')
    witness = term['identity_witness']
    seen = False
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2022.csv.gz'):
            if (row['session'], row['security_id']) == (witness['session'], SID):
                need(not seen, 'UNIQUE_FMTX_SOURCE_ROW')
                require_witness(row, witness)
                need(row['issuer_id'] == 'SEC_CIK:1538927' and row['security_type_eligible'] == '1', 'FMTX_PROVIDER_METADATA_UNCHANGED')
                seen = True
    need(seen, 'ACTUAL_FMTX_FROZEN_WITNESS')
    material = dict(schema=REFERENCE, arm=arm, parent_outer_sha256=cp['sha256'], terms=[term],
        original_catalog_previously_adopted=False, original_book_authority_reused=False,
        provider_metadata_upgraded=False, actual_exchange_agent_payment_time_claimed=False)
    hydrated = root/'own-fmtx-input-facts.json'
    save(hydrated, material)
    document = dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=[dict(reference=REFERENCE, description=term['description'], sha256=sha(hydrated.read_bytes())),
            dict(reference=REFERENCE+'/catalog', description='Unchanged source-bound catalog, not prior adoption.', sha256=CATALOG_SHA),
            dict(reference=REFERENCE+'/compiler', description='Exact own future-input compiler.', sha256=sha(Path(__file__).read_bytes())),
            dict(reference=REFERENCE+'/validator', description='Original mandatory cash calendar validator.', sha256=LOADER_SHA),
            dict(reference=term['primary_source'], description=term['description'], sha256=None)],
        suppress=original.suppressions(cp, [term]), add=[deepcopy(term['added'])])
    overlay = root/'own-fmtx-overlay.json'
    save(overlay, document)
    loaded = load_repair(overlay, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'fmtx-input-qualification'
    audit.mkdir()
    original.qualify(cp, material, {}, actions, loaded, overlay, audit)
    return ['--repair-overlay', str(overlay)], material


def observer(root, cp, material):
    hosted()
    own_scope(cp, material['arm'])
    from system_campaign_financial_future import ActualEvents
    term, = material['terms']
    need(digest(term) == TERM_SHA and material['parent_outer_sha256'] == cp['sha256']
         and not material['original_catalog_previously_adopted'] and not material['original_book_authority_reused']
         and not material['provider_metadata_upgraded'] and not material['actual_exchange_agent_payment_time_claimed'], 'ACTUAL_OWN_FMTX_FUTURE_SCOPE')
    class OwnFmtxEvents(ActualEvents):
        def __init__(self):
            self.out, self.arm = root, material['arm']
            self.terms = {(term['added']['session'], SID): deepcopy(term['added'])}
            self.scopes = []
            self.saved, self.current = [], None
    return OwnFmtxEvents()
