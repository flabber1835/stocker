"""Pure admission predicates for the explicit post-schema PAPER canonical proof.

Delivery and future receipt consumers must admit the same immutable evidence.
These functions perform no IO, read no environment, and do not renew a clock.
"""
from __future__ import annotations

from datetime import datetime
import re

from .model import (ACCESS_PATH_SCHEMA, POST_SCHEMA_ACCESS_PATH,
                    canonical_proof_phase, digest, handoff_mode, require)


def _sha256(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def require_contract(request, subject, artifacts):
    """Admit the exact request, predecessor fact and migration-only contract."""
    require(request.get('schema')==ACCESS_PATH_SCHEMA
        and canonical_proof_phase(request)==POST_SCHEMA_ACCESS_PATH
        and handoff_mode(request)=='PRE_OPEN' and subject==digest(request),
        'ACCESS_PATH_CANONICAL_REQUEST_CHANGED')
    contract=artifacts.get('access_path_canonical_contract')
    retained=artifacts.get('predecessor_canonical_proof')
    state=artifacts.get('preserved')
    require(isinstance(contract,dict) and set(contract)=={
        'schema','authority_effect','request_sha256','operation_id','predecessor','candidate',
        'state_sha256','predecessor_proof_sha256','system_identifier',
        'operational_installation_sha256','access_contract_sha256'}
        and isinstance(retained,dict) and bool(retained) and isinstance(state,dict),
        'ACCESS_PATH_CANONICAL_CONTRACT_INVALID')
    require(contract['schema']=='sentinel.checkpoint-access-bootstrap/1'
        and contract['authority_effect']=='NONE'
        and contract['request_sha256']==subject
        and contract['operation_id']==request['operation_id']
        and contract['predecessor']=={key:request['predecessor'][key] for key in ('commit','image')}
        and contract['candidate']=={key:request['candidate'][key]
                                   for key in ('commit','image','source_identity')}
        and contract['state_sha256']==digest(state)
        and contract['predecessor_proof_sha256']==digest(retained)
        and contract['system_identifier']==state.get('system')==request['predecessor']['system']
        and all(_sha256(contract[key]) for key in
                ('operational_installation_sha256','access_contract_sha256')),
        'ACCESS_PATH_CANONICAL_CONTRACT_CHANGED')
    return contract


def require_installation(contract, installed):
    """Admit a marker/catalog result bound to the same preflight contract."""
    require(isinstance(installed,dict) and set(installed)=={
        'schema','authority_effect','request_sha256','state_sha256','system_identifier',
        'operational_installation_sha256','access_contract_sha256','access_installation_sha256'}
        and installed['schema']=='sentinel.checkpoint-access-installed/1'
        and installed['authority_effect']=='NONE'
        and all(installed[key]==contract[key] for key in ('request_sha256','state_sha256',
            'system_identifier','operational_installation_sha256','access_contract_sha256'))
        and _sha256(installed['access_installation_sha256']),
        'ACCESS_PATH_CANONICAL_INSTALLATION_CHANGED')
    return installed


def require_qualification(request, subject, artifacts):
    """Require the actual complete equal proof before startup or later reuse."""
    contract=require_contract(request,subject,artifacts)
    qualification=artifacts.get('access_path_canonical_qualification')
    proof=artifacts.get('canonical_proof')
    require(isinstance(qualification,dict) and set(qualification)=={
        'schema','authority_effect','request_sha256','state_sha256','contract_sha256',
        'installation','canonical_proof_sha256','qualified_at'}
        and isinstance(proof,dict) and bool(proof),
        'ACCESS_PATH_CANONICAL_QUALIFICATION_REQUIRED')
    require(qualification['schema']=='sentinel.checkpoint-access-canonical-qualification/1'
        and qualification['authority_effect']=='NONE'
        and qualification['request_sha256']==subject
        and qualification['state_sha256']==contract['state_sha256']
        and qualification['contract_sha256']==digest(contract)
        and qualification['canonical_proof_sha256']==digest(proof)
        and proof==artifacts['predecessor_canonical_proof'],
        'ACCESS_PATH_CANONICAL_QUALIFICATION_CHANGED')
    require_installation(contract,qualification['installation'])
    try:
        instant=datetime.fromisoformat(qualification['qualified_at'])
    except (TypeError,ValueError):
        require(False,'ACCESS_PATH_CANONICAL_QUALIFICATION_TIME_INVALID')
    require(instant.utcoffset() is not None,'ACCESS_PATH_CANONICAL_QUALIFICATION_TIME_INVALID')
    return qualification
