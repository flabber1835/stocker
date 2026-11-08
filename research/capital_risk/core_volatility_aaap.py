"""Existing disclosed AAAP tender model on the alternative's own predecessor."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from core_volatility_source import need, sha
from full_system_core import hosted
from full_system_benchmark import save

REFERENCE = 'research:core-volatility-20261108/original-aaap-tender-model/1'
PARENT = 'c35a5197874eb57190d2f47433390e1ebff6fd189f50e82282b4a6568eefe13b'
SID = '554122275008038119'


def own_position(cp, arm):
    need(arm == 'VOL075' and cp['sha256'] == PARENT and cp['source_cursor'] == '2018-01-31'
         and cp['completed'] == 21, 'EXACT_AAAP_OWN_PREDECESSOR')
    positions = [e for e in cp['run']['state']['wealth_core']['episodes'].values() if e['security_id'] == SID]
    need(len(positions) == 1 and positions[0]['ticker'] == 'AAAP1'
         and positions[0]['current_shares'] == 31 and positions[0]['entry_date'] == '2017-12-12',
         'ACTUAL_OWN_31_ADS_NOT_ORIGINAL_VARIANT_POSITIONS')
    return deepcopy(positions)


def prepare(cp, root, arm):
    hosted()
    positions = own_position(cp, arm)
    import system_campaign_financial_future as original
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding.repair import load_repair
    from system_campaign_2021_completions_facts import require_witness
    codec, catalog, selected = original.own_cash_selection('P05', '2018-01-31')
    term, = deepcopy(selected)
    original.research_tender_term(term)
    original.completion_session(term, axis())
    need(term['ticker'] == 'AAAP1' and term['security_id'] == SID
         and term['identity_witness']['security_type_eligible'] == '0', 'EXACT_ORIGINAL_AAAP_SOURCE_AND_MODEL')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native, = [v for v in actions.terminal.get('2018-02-09', ()) if v.security_id == SID]
    need(original.digest(asdict(native)) == term['native_term_sha256']
         and not native.completeness(0)[0], 'EXACT_ORIGINAL_INCOMPLETE_AAAP_NATIVE')
    need(not [v for v in actions.terminal.get('2018-02-01', ()) if v.security_id == SID], 'NO_CONFLICTING_AAAP_TERM')
    witness = term['identity_witness']
    seen = []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2018.csv.gz'):
            if (row['session'], row['security_id']) == (witness['session'], SID):
                require_witness(row, witness)
                seen.append(row)
    need(len(seen) == 1 and witness['session'] == cp['source_cursor'], 'OWN_DEADLINE_FROZEN_SOURCE_WITNESS')
    material = {'schema': REFERENCE, 'arm': arm, 'parent_outer_sha256': cp['sha256'],
                'own_positions': positions, 'terms': [term], 'original_book_authority_reused': False,
                'existing_research_tender_assumption_unchanged': True, 'actual_settlement_claimed': False}
    path = root/'aaap-own-input-model.json'
    save(path, material)
    document = {'schema': 'terminal-repair/1', 'predecessor_checkpoint_sha256': cp['run']['checkpoint_sha256'],
        'source_evidence': [
            dict(reference=REFERENCE, description=term['description'], sha256=sha(path.read_bytes())),
            dict(reference=REFERENCE+'/compiler', description='Exact own-predecessor research input compiler.', sha256=sha(Path(__file__).read_bytes())),
            dict(reference=REFERENCE+'/original-validator', description='Unchanged disclosed tender model, source selection and canonical input qualifier.', sha256=sha(Path(original.__file__).read_bytes())),
            dict(reference=REFERENCE+'/original-catalog', description='Original qualified source fact and declared participation/availability/fee assumptions.', sha256=codec.catalog_sha),
            dict(reference=term['primary_source'], description=term['description'], sha256=None)],
        'suppress': original.suppressions(cp, [term]), 'add': [deepcopy(term['added'])]}
    overlay = root/'aaap-own-input-overlay.json'
    save(overlay, document)
    loaded = load_repair(overlay, resume_session=cp['source_cursor'],
                         predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'aaap-input-qualification'
    audit.mkdir()
    original.qualify(cp, material, {}, actions, loaded, overlay, audit)
    return ['--repair-overlay', str(overlay)], material


def observer(root, cp, material):
    """Reuse unchanged actual canonical delegation and cash/ledger postconditions."""
    hosted()
    from system_campaign_financial_future import ActualEvents, RESEARCH_TENDER, research_tender_term
    own_position(cp, material['arm'])
    term, = material['terms']
    research_tender_term(term)
    need(term['recognition_rule'] == RESEARCH_TENDER and material['parent_outer_sha256'] == cp['sha256']
         and not material['original_book_authority_reused'] and not material['actual_settlement_claimed'],
         'OWN_TENDER_OBSERVER_NO_SOURCE_ONLY_OR_FOREIGN_BOOK_SCOPE')
    class OwnTenderEvents(ActualEvents):
        def __init__(self):
            # This scope contains only the typed tender model, so no unowned
            # closing-source capability is introduced or silently omitted.
            self.out, self.arm = root, material['arm']
            self.terms = {(term['added']['session'], SID): deepcopy(term['added'])}
            self.scopes = []
            self.saved, self.current = [], None
    return OwnTenderEvents()
