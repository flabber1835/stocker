"""Generic v2 source gates, loaded input view and independent child oracle.

These are input/DATA primitives for the shared hosted v2 adapter. No local
canonical financial operation is available here. P06 v1 sources remain exact.
"""
import ast
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from urllib.parse import urlparse

from system_campaign_financial_compound_input_v2 import sha,digest,encoded,need,hash_value,consideration,validate_model

HERE=Path(__file__).parent
CATALOG_FILE='system-campaign-compound-input-v2-facts.json'
CATALOG_SHA='0fe8dbf7d5678955f8fd23b4d32d1b6a3c54f33bda03098cf5b2e71ef17ad74f'
SOURCE_V2='system_campaign_financial_distribution_source_v2.py'
V1_RUNTIME_SHA='a46d21598580dc78d5b0bdf471f64aa1d6148e0d668c5b858ce61e51e2245da7'


def primary_binding(record):
    """Bind the explicitly reviewed economic interpretation, preserving raw identity."""
    p=record['primary_extraction'];m=validate_model(record['research_assumption'])
    url=urlparse(p['primary_source'])
    need(p['schema']=='research.single-in-kind-continuing-parent-primary-extraction/1'
         and url.scheme=='https' and bool(url.netloc)
         and record['reference'].startswith(p['primary_source']+' | ')
         and p['distribution_session']==m.actual_distribution_session
         and Fraction(p['child_shares_per_original_parent'])==Fraction(m.child_shares_per_original_parent)
         and p['continuing_parent_ratio']==m.continuing_parent_ratio=='1'
         and p['additional_cash_per_original_parent']=='0'
         and p['single_in_kind_distribution'] is p['fractional_cash_in_lieu_only'] is True
         and p['equivalent_native_economic_representation']==m.native_relationship
         and p['frozen_parent_identity_upgraded'] is False,
         'COMPOUND_V2_PRIMARY_SINGLE_CHILD_CONTINUING_PARENT_NO_ADDITIONAL_CASH')
    return True


def qualified_record(arm='P07'):
    raw=(HERE/CATALOG_FILE).read_bytes()
    need(hash_value(CATALOG_SHA) and sha(raw)==CATALOG_SHA,'COMPOUND_V2_CLOSED_CATALOG_PIN_REQUIRED')
    catalog=json.loads(raw)
    need(catalog['schema']=='research.selected-compound-distribution-input/2'
         and catalog['canonical_financial_source_changed'] is catalog['production_contacted'] is False,
         'COMPOUND_V2_SELECTED_INPUT_ONLY_CATALOG')
    records=[r for r in catalog['records'] if r['arm']==arm];need(len(records)==1,'COMPOUND_V2_ONE_EXACT_SELECTED_RECORD')
    r,=records;p=r['source_proof']
    need(r['status']=='CLOSED_SOURCE_DATA_QUALIFIED_INPUT' and r['input_kind']=='DISTRIBUTION_ONLY'
         and isinstance(p,dict) and p.get('independent_DATA_passed') is p.get('independent_qualification_passed') is True
         and type(p.get('run_id')) is int and p['run_id']>0 and type(p.get('artifact_id')) is int and p['artifact_id']>0
         and type(p.get('head')) is str and len(p['head'])==40 and set(p['head'])<=set('0123456789abcdef')
         and all(hash_value(p.get(k)) for k in ('zip_sha256','payload_sha256','payload_digest','producer_sha256',
             'distribution_producer_sha256','scope_sha256','independent_data_review_sha256','independent_qualification_sha256'))
         and p['scope_sha256']==digest(r['source_scope'])
         and r['source_scope']['parent_outer_sha256']==r['parent_outer_sha256']
         and r['source_scope']['parent_cursor']==r['parent_cursor']
         and r['parent_cursor']<r['research_assumption']['recognition_session']
         and r['source_module_file']==SOURCE_V2
         and all(hash_value(r.get(k)) for k in ('parent_outer_sha256','parent_inner_sha256','parent_input_sha256',
             'parent_root_admission_sha256','source_bindings_sha256')),
         'COMPOUND_V2_CLOSED_SOURCE_DATA_AND_OWN_PARENT_PINS_REQUIRED')
    need(sha((HERE/SOURCE_V2).read_bytes())==p['distribution_producer_sha256'],
         'COMPOUND_V2_IMMUTABLE_CLOSED_SOURCE_GENERATION')
    primary_binding(r)
    return r


def activation_descriptor(loaded,binding,source_proof):
    need(source_proof.get('independent_DATA_passed') is source_proof.get('independent_qualification_passed') is True
         and hash_value(source_proof.get('independent_data_review_sha256'))
         and source_proof['independent_data_review_sha256']==binding['source_DATA_sha256']
         and source_proof['scope_sha256']==binding['source_scope_sha256'],
         'COMPOUND_V2_LOADED_VIEW_REQUIRES_SAME_CLOSED_SOURCE_DATA')
    ordinary=loaded.earliest_affected_session;distribution=binding['spin']['session'];cursor=binding['parent_cursor']
    day=min(ordinary,distribution)
    before=loaded.model_dump(mode='json',by_alias=True)
    need(binding['input_kind']=='DISTRIBUTION_ONLY' and binding['terminal'] is None
         and before['schema']=='terminal-repair/1' and (before['suppress'] or before['add'])
         and loaded._resume_session==cursor and hash_value(loaded.sha256)
         and loaded._document_sha256==digest(before) and cursor<day,
         'COMPOUND_V2_ORIGINAL_NONEMPTY_PARSED_REPAIR_AND_UNCONSUMED_MINIMUM_BOUNDARY')
    return dict(schema='research.qualified-composite-loaded-input-view/1',parent_outer_sha256=binding['parent_outer_sha256'],
        parent_cursor=cursor,ordinary_file_sha256=loaded.sha256,ordinary_document_sha256=digest(before),
        ordinary_earliest_session=ordinary,distribution_session=distribution,earliest_affected_session=day,
        binding_sha256=digest(binding),source_DATA_sha256=binding['source_DATA_sha256'])


def qualified_loaded_view(loaded,binding,source_proof,activation):
    """Called only AFTER the unchanged canonical nonempty loader has succeeded."""
    expected=activation_descriptor(loaded,binding,source_proof)
    need(activation==expected,'COMPOUND_V2_EXACT_QUALIFIED_LOADED_VIEW_DESCRIPTOR')
    before=deepcopy(loaded.model_dump(mode='json',by_alias=True));private=deepcopy(loaded.__pydantic_private__)
    original_type=type(loaded);ordinary=expected['ordinary_earliest_session'];day=expected['earliest_affected_session']
    source_sha=expected['ordinary_file_sha256'];cursor=expected['parent_cursor']
    class QualifiedCompositeRepair(original_type):
        @property
        def earliest_affected_session(self):
            need(self.model_dump(mode='json',by_alias=True)==before and self.sha256==source_sha
                 and self._resume_session==cursor and self._document_sha256==digest(before)
                 and super().earliest_affected_session==ordinary,
                 'COMPOUND_V2_LOADED_VIEW_FIELDS_AND_CANONICAL_PRIVATE_COMMITMENTS_UNCHANGED')
            return day
    view=QualifiedCompositeRepair.model_validate(before)
    view.__pydantic_private__.update(private)
    need(view.model_dump(mode='json',by_alias=True)==before and view.__pydantic_private__==private
         and view.sha256==loaded.sha256 and view.earliest_affected_session==day,
         'COMPOUND_V2_LOADED_VIEW_PRESERVES_ALL_SERIALIZED_AND_PRIVATE_FIELDS')
    return view


def original_role(binding,state):
    return sum((Fraction(str(e['current_shares'])) for e in state['episodes'].values()
                if e['security_id']==binding['spin']['parent_security_id']),Fraction(0))


def spin_postcondition(binding,before,after,ledger_before,ledger_after,result,cost_bps):
    """Reuse every v1 canonical receipt/sale/reference/lot predicate unchanged."""
    import system_campaign_financial_compound_runtime as original
    raw=Path(original.__file__).read_bytes()
    need(sha(raw)==V1_RUNTIME_SHA,'COMPOUND_V2_IMMUTABLE_V1_CHILD_POSTCONDITION_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='spin_postcondition']
    namespace=dict(vars(original),consideration=consideration,original_role=original_role)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<unchanged-v1-child-postcondition-with-v2-child-only-oracle>','exec'),namespace)
    return namespace['spin_postcondition'](binding,before,after,ledger_before,ledger_after,result,cost_bps)


def retained_payload_proof(original,current,*,payload_raw,descriptor,prior_certificate_raw,current_certificate_raw):
    """Generational retention DATA obligation; no old proof is reexecuted."""
    need(original['base']==current['base'] and original['sha256']==descriptor['parent_outer_sha256']
         and original['source_cursor']==descriptor['parent_cursor']<=current['source_cursor']
         and sha(payload_raw)==descriptor['payload_sha256']
         and descriptor['APHA_projection_source_sha256']=='2165e64a961bf0ee44c8f19ac2d6ec65059cc92a2b4154ad735685d29e120777'
         and descriptor['branch_source_sha256']=='b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef'
         and len(prior_certificate_raw.splitlines())==descriptor['retained_certificate_rows']==384
         and current_certificate_raw[:len(prior_certificate_raw)]==prior_certificate_raw,
         'COMPOUND_V2_SAME_OWN_GENERATION_PAYLOAD_AND_ALL384_BRANCH_CERTIFICATE_BYTES')
    return True
