"""A future-only ordinary canonical repair; no alternate terminal parser."""
from copy import deepcopy
import json
from pathlib import Path
import zipfile

from system_campaign_p10_ahl2_contract import (SID, CURSOR, NATIVE, AFFECTED, encoded, digest, sha, need)

FIELDS = {'schema', 'predecessor_checkpoint_sha256', 'source_evidence', 'suppress', 'add'}


def identity_valid(row, witness):
    need(digest(row) == witness['source_observation_sha256']
         and all(row[k] == v for k,v in witness.items() if k != 'source_observation_sha256')
         and row['security_id'] == SID and row['ticker'] == 'AHL2'
         and row['issuer_id'] == 'SEC_UNKNOWN:' + SID and row['security_type_eligible'] == '0',
         'P10_EXACT_FROZEN_RAW_ALIAS_PREIMAGE_NO_CLASSIFICATION_UPGRADE')


def source_witness(spec):
    from full_system_core import hosted
    hosted()
    from research.pooled_input_support import inputs
    from system_campaign_discovery_context import material
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native = [x for x in actions.terminal.get(NATIVE, ()) if x.security_id == SID]
    need(len(native) == 1 and digest(material(native[0])) == spec['native_term']['native_term_sha256'],
         'P10_ACTUAL_OWN_NATIVE_TERMINAL_PREIMAGE_BEFORE_RESTORE')
    witness = spec['identity_witness']
    seen, absent_day = [], []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2019.csv.gz'):
            if row['security_id'] != SID:
                continue
            if row['session'] == NATIVE:
                identity_valid(row, witness)
                seen.append(deepcopy(row))
            elif row['session'] == AFFECTED:
                absent_day.append(row)
    need(len(seen) == 1 and not absent_day, 'P10_EXACT_UNIQUE_LAST_SOURCE_WITNESS_AND_NO_FEB15_QUOTE')
    return dict(schema='research.p10-own-source-subset-proof/1', native_term=material(native[0]),
        native_term_sha256=digest(material(native[0])), raw_identity_observation=seen[0],
        raw_identity_observation_sha256=digest(seen[0]), frozen_classifications_unchanged=True,
        no_feb15_source_observation=True, whole_archive_admission_reused=True,
        another_arm_catalog_adopted=False, financial_authority=False)


def expected_document(spec):
    row = spec['native_term']
    term = deepcopy(row['added'])
    need(term['session'] == AFFECTED and term['security_id'] == SID and term['kind'] == 'CASH_MERGER'
         and type(term['cash_per_share']) is float and term['cash_per_share'] == 42.75,
         'P10_EXACT_RETAINED_PRIMARY_ORDINARY_CASH_AND_OPEN_CLOCK')
    return dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=spec['runtime_checkpoint_sha256'],
                source_evidence=[dict(reference=row['primary_source'],
                    description='Retained primary ordinary-share completion extraction; historic AHL2 alias, SEC_UNKNOWN and ineligibility unchanged.',
                    sha256=spec['primary_fact_source']), dict(
                    reference='https://www.miaxglobal.com/sites/default/files/alert-files/AHL_Merger_44575.pdf',
                    description='Retained OCC44575 primary clock: consummated before February15,2019 opening; ordinary stock consideration42.75USD. No option settlement rule or statutory minute imported.',
                    sha256=None)],
                suppress=[dict(session=NATIVE, security_id=SID, term_sha256=row['native_term_sha256'])], add=[term])


def validate_document(value, spec):
    need(type(value) is dict and set(value) == FIELDS and value == expected_document(spec),
         'P10_ONLY_EXACT_OWN_FOURTH_ORDINARY_DOCUMENT')
    return value


def document_bytes(spec):
    return (json.dumps(expected_document(spec), sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def load(path, spec, canonical_loader):
    raw = Path(path).read_bytes()
    need(raw == document_bytes(spec), 'P10_EXACT_RAW_FOURTH_INPUT_BYTES')
    validate_document(json.loads(raw), spec)
    obj = canonical_loader(path, resume_session=CURSOR,
                           predecessor_checkpoint_sha256=spec['runtime_checkpoint_sha256'])
    need(obj.sha256 == sha(raw) and obj.earliest_affected_session == NATIVE,
         'P10_ACTUAL_CANONICAL_REPAIR_RAW_SHA_AND_FUTURE_SUPPRESSION')
    need(digest(obj.model_dump(mode='json', by_alias=True)) == digest(expected_document(spec)),
         'P10_ACTUAL_CANONICAL_TYPED_MODEL_IDENTITY_DISTINCT_FROM_RAW_FILE_SHA')
    return obj


def descriptor(obj, spec):
    need(obj.sha256 == sha(document_bytes(spec)), 'P10_CANONICAL_LOADED_OBJECT_RAW_IDENTITY')
    return dict(filename=obj.sha256 + '.json', sha256=obj.sha256, resume_session=CURSOR,
                predecessor_checkpoint_sha256=spec['runtime_checkpoint_sha256'])


def packet_change(before, after, *, spec, material):
    """Bind the exact sparse fourth-input effect around canonical apply_repair."""
    original, changed = material(before), material(after)
    day = original['day']
    a, b = deepcopy(original), deepcopy(changed)
    old_terms, new_terms = a.pop('terminal'), b.pop('terminal')
    need(a == b, 'P10_ALL_QUOTES_BARS_DIVIDENDS_SPINS_AND_SOURCE_FIELDS_UNCHANGED')
    if day == NATIVE:
        selected = [x for x in old_terms if x['security_id'] == SID]
        need(len(selected) == 1 and digest(selected[0]) == spec['native_term']['native_term_sha256']
             and new_terms == [x for x in old_terms if x['security_id'] != SID],
             'P10_ONLY_EXACT_NATIVE_FEB14_TERMINAL_SUPPRESSED')
    elif day == AFFECTED:
        need(not any(x['security_id'] == SID for x in old_terms)
             and sorted(new_terms, key=lambda x:x['security_id']) == sorted(
                 old_terms + [expected_document(spec)['add'][0]], key=lambda x:x['security_id']),
             'P10_ONLY_COMPLETE_FEB15_CONTRACTUAL_CASH_ADDED')
        need(not any(x['security_id'] == SID for x in original['bars']), 'P10_NO_FEB15_AHL2_SOURCE_BAR_OR_PRICE_INVENTED')
    else:
        need(original == changed, 'P10_NO_OTHER_PACKET_OR_DATE_CHANGED')
    return dict(session=day, original_packet_sha256=digest(original), candidate_packet_sha256=digest(changed),
                all_nonterminal_fields_exact=True, only_declared_terminal_change=True)
