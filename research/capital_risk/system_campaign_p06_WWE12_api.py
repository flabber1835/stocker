"""Original StockCalendar and27-share gate, independently prepared before finance."""
import json
from pathlib import Path
import system_campaign_p06_WWE_admission as authority
import system_campaign_p06_WWE_source_asset as asset
import system_campaign_p06_WWE12_stock as stock
import system_campaign_p06_WWE27_qualifiers as roles
import system_campaign_p06_WWE12_models as models
import system_campaign_p06_WWE12_data as data
import system_campaign_wwe_facts as facts
from system_campaign_bounded_sensor_origin_v2 import exact
from system_campaign_sprint_facts import PACKET_SOURCE_PATH
HERE=Path(__file__).parent
PACKETS='wwe-packet-qualification.json'
CANONICAL='wwe-canonical-qualification.json'
RECEIPT='p06-WWE-zero-financial-preparation.json'

def prepare(parent,old,out,request,*,spec):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest
    authority.parent(parent,spec);old,out=Path(old),Path(out)
    asset.stage_source(HERE,out,request)
    catalog=HERE/facts.CATALOG;facts.validate(json.loads(catalog.read_bytes()))
    obj,loaded,path=stock.bound_build(old,out,request)(parent,old,out,catalog)
    objects=[backtest.load_repair(old/'book/repairs'/d['filename'],resume_session=d['resume_session'],
        predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in parent['repairs']]
    gate_request=dict(qualified_packet_source_sha256=parent['base']['sources'][PACKET_SOURCE_PATH])
    roles.bound('qualify')(out,parent,obj,loaded,objects,gate_request)
    data.need(path==out/models.OVERLAY and loaded.earliest_affected_session=='2023-09-11'
        and loaded.sha256==data.sha(path.read_bytes()) and json.loads(path.read_bytes())==models.document(parent,lambda n:(out/n).read_bytes()),
        'P06_WWE12_ENTIRE_ORIGINAL_PREPARED_STOCK_DOCUMENT_AND_UNCONSUMED_DATE')
    return path,loaded

def receipt(parent,spec,root):
    authority.parent(parent,spec);root=Path(root)
    packet=json.loads((root/PACKETS).read_bytes());canonical=json.loads((root/CANONICAL).read_bytes())
    data.need(packet['actual_packet_checks']==2 and packet['actual_stock_or_mixed_terms']==1
        and packet['original_incomplete_guards']==1 and packet['cumulative_retained_inputs_applied'] is True
        and packet['original_packets_unchanged'] is True and packet['missing_delivery_quote_refused'] is True
        and packet['wrong_delivered_identity_refused'] is True and packet['financial_sessions_advanced']==0,
        'P06_WWE12_TWO_REAL_PACKETS_ALL_OLD_INPUTS_AND_ORIGINAL_REFUSALS')
    data.need(canonical['status']=='ACTUAL_OWN_WWE_TO_TKO_CANONICAL_CONVERSION_QUALIFIED'
        and canonical['parent_checkpoint_sha256']==parent['sha256'] and canonical['original_shares']==canonical['delivered_shares']==27
        and canonical['cash_delta']==canonical['fractional_cash_paid']==canonical['financial_sessions_advanced']==0
        and all(canonical[k] is True for k in ('actual_parent_roundtrip','actual_packets_and_prior_inputs_qualified',
            'actual_once_only_and_missing_signal_basis_refusals','source_state_unchanged','qualification_copy_only',
            'actual_resumed_session_proof_still_required')),
        'P06_WWE12_REAL_27_FOR_27_ONCE_ONLY_CANONICAL_COPY_GATE')
    data.need(json.loads((root/models.OVERLAY).read_bytes())==models.document(parent,lambda n:(root/n).read_bytes()),
        'P06_WWE12_PREPARATION_COMPLETE_STOCK_DOCUMENT_RECONSTRUCTION')
    return dict(schema='research.P06-WWE12-zero-financial-preparation/1',passed=True,arm='P06',root_admission_sha256=data.ROOT,
        parent_outer_sha256=parent['sha256'],earliest_affected_session='2023-09-11',
        files={n:dict(bytes=len((root/n).read_bytes()),sha256=data.sha((root/n).read_bytes())) for n in (models.OVERLAY,models.PRIVATE,PACKETS,CANONICAL)},
        parent_unchanged=True,checkpoint_adopted=False,financial_sessions_advanced=0)

def preflight(parent,out,spec,old,request):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,runtime
    out=Path(out);before=data.encoded(parent);forbidden=[out/'book/checkpoint.json.gz',out/models.DIRECTORY/'checkpoint.json.gz']
    data.need(not any(p.exists() for p in forbidden),'P06_WWE12_PREPARATION_STARTS_WITHOUT_FINANCIAL_OR_NEUTRAL_BOOK')
    def refuse(*a,**k):raise ValueError('P06_WWE12_PREFLIGHT_CANNOT_ADVANCE_FINANCIAL_SESSIONS')
    saved=backtest.main,runtime.advance
    try:
        backtest.main=runtime.advance=refuse
        prepare(parent,old,out,request,spec=spec)
    finally:backtest.main,runtime.advance=saved
    data.need(data.encoded(parent)==before and not any(p.exists() for p in forbidden),'P06_WWE12_NO_PREFLIGHT_PARENT_MUTATION_OR_ADOPTION')
    result=receipt(parent,spec,out);exact(out/RECEIPT,data.encoded(result));return result

def require_preflight(parent,spec,proof,root):
    root=Path(root);expected=receipt(parent,spec,root)
    data.need(proof['composite_preparation']==expected==json.loads((root/RECEIPT).read_bytes()),
        'P06_WWE12_EXACT_STOPPED_SOURCE_AND27_GATE_PREPARATION_BEFORE_FINANCE')
    return True

def review_input(parent,spec,evidence,out,request):
    from full_system_core import hosted
    hosted();evidence,out=Path(evidence),Path(out)
    prepare(parent,Path('/old'),out,request,spec=spec)
    for n in (models.OVERLAY,models.PRIVATE,PACKETS,CANONICAL):
        data.need((out/n).read_bytes()==(evidence/n).read_bytes(),'P06_WWE12_INDEPENDENT_COMPLETE_STOCK_REHYDRATION_AND_GATES:'+n)
    return True

def source_names():return (Path(__file__).name,*stock.source_names(),*roles.source_names(),*models.source_names(),
    'system_campaign_registry_extension.py','system-campaign-ordinary-catalog-registry.json')
