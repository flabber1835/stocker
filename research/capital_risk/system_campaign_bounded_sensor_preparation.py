"""Hosted zero-transition typed parser/packet/cloud qualification only."""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

from system_campaign_bounded_sensor_input import InputCodec,need,sha,digest
from system_campaign_bounded_sensor_catalog import encoded,load
from system_campaign_bounded_sensor_lifecycle_data import document,validate_document,DOCUMENT,SOURCE
from system_campaign_bounded_sensor_hydration import hydrate
from system_campaign_bounded_sensor_binding import basis

HERE=Path(__file__).parent
CATALOG='P03-own462-DOVA-source-bound-input-catalog-v1.json'
CATALOG_SHA='a74c1f8c928be7b0dca35ee2c51aee803509c84024378bf2897a862a67b3d2a7'
QUALIFICATION='bounded-sensor-input-preparation.json'

def source_names():
    from system_campaign_bounded_sensor_semantics import FILES
    return tuple(sorted(FILES|{CATALOG,'system_campaign_bounded_sensor_event_review.py',
        'system_campaign_bounded_sensor_hydration.py','system_campaign_bounded_sensor_preparation.py'}))

def selected(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P03' and spec.get('root_admission_sha256')=='2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0'

def catalog():
    need(sha((HERE/CATALOG).read_bytes())==CATALOG_SHA,'BOUNDED_PREPARATION_EXACT_INPUT_GENERATION')
    return load(HERE/CATALOG)

def write_exact(path,raw):
    path=Path(path)
    if path.exists():need(path.read_bytes()==raw,'BOUNDED_PREPARATION_EXISTING_EXACT_DOCUMENT')
    else:
        with path.open('xb') as stream:stream.write(raw)

@contextmanager
def no_financial_transitions():
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,runtime
    main,advance=backtest.main,runtime.advance
    def refuse(*args,**kwargs):raise ValueError('BOUNDED_PREPARATION_CANNOT_ADVANCE_FINANCIAL_STATE')
    backtest.main=runtime.advance=refuse
    try:yield
    finally:backtest.main,runtime.advance=main,advance

def qualify_packets(cp,path,loaded,codec,native,value,out):
    from full_system_core import hosted
    hosted()
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import backtest
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    from system_campaign_sprint_facts import qualify_packet_schema,published_packet
    qualify_packet_schema(Packet,cp['base']['sources']['research/pooled_input_support/adapter.py'])
    event=value['event'];source=value['market_source'];sid=event['security_id'];checks=0
    prior=SimpleNamespace(median5=dict(selected=[sid]),wealth_core=dict(episodes={}),pending=[],
        last_processed_session=event['prior_session'],feed=dict(series={sid:dict(signal_basis_anchor=(event['prior_session'],
        float(source['raw_prior_row']['raw_close']),float(source['raw_prior_row']['signal_close'])))}))
    for day in sorted({event['native_session'],event['effective_session']}):
        bar=vendor(source['raw_event_row']) if day==event['effective_session'] else None
        original=Packet(day,(bar,) if bar is not None else (),{},{},1.,{},(native,) if day==event['native_session'] else (),())
        before=asdict(original);fixed=backtest.apply_repair(original,loaded)
        expected=dict(before)
        if event['native_session']!=event['effective_session']:
            expected['terminal']=[] if day==event['native_session'] else [dict(asdict(native),session=day)]
        actual=asdict(fixed)
        # dataclasses.asdict retains tuple containers on the frozen packet.
        if 'terminal' in expected:expected['terminal']=tuple(expected['terminal'])
        need(asdict(original)==before and actual==expected,'BOUNDED_PREPARATION_ONLY_EXPLICIT_TERMINAL_RECALENDAR')
        if day==event['effective_session']:
            term,=[t for t in fixed.terminal if t.security_id==sid]
            need(term.cash_per_share is None and not term.completeness(0)[0], 'BOUNDED_PREPARATION_NATIVE_REMAINS_INCOMPLETE')
            published=published_packet(fixed)
            try:terminal_returns.values(prior=prior,published=published)
            except ValueError as error:
                need(str(error).startswith('incomplete leadership cash terminal:'),'BOUNDED_PREPARATION_ORIGINAL_INCOMPLETE_REFUSAL')
            else:raise ValueError('BOUNDED_PREPARATION_ORIGINAL_INCOMPLETE_GUARD_MISSING')
            proof,interval=basis(prior,published,event,source,native)
            need(proof['selected'] is True and interval is not None,'BOUNDED_PREPARATION_ACTUAL_SELECTED_BASIS')
        checks+=1
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(event['native_session'],cp['run']['checkpoint_sha256'])):
        try:backtest.load_repair(path,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('BOUNDED_PREPARATION_PARSER_FALSIFIER_ACCEPTED')
    return dict(actual_packet_checks=checks,wrong_predecessor_and_consumed_cursor_refused=True,
        original_incomplete_guard_retained=True,no_cash_or_right_price_created=True,actual_selected_signal_range=interval)

def prepare(cp,out,spec):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_partial import root_spec
    from research.pooled_vacancy_funding import backtest
    import system_campaign_financial_branches as original
    need(selected(spec),'BOUNDED_PREPARATION_EXACT_EXPLICIT_OWN_ROOT')
    value=catalog();out=Path(out)
    need((cp['sha256'],cp['source_cursor'],cp['completed'])==(value['parent_outer_sha256'],value['parent_cursor'],value['parent_completed'])
         and cp['repairs']==value['parent_descriptors'],'BOUNDED_PREPARATION_EXACT_FULL_OWN_PARENT')
    forbidden=(out/'book/checkpoint.json.gz',out/'input-adoption/checkpoint.json.gz')
    need(not any(p.exists() for p in forbidden),'BOUNDED_PREPARATION_STARTS_WITHOUT_NEW_CHECKPOINT')
    before=encoded(cp)
    with no_financial_transitions():
        native,source=hydrate(value,out/SOURCE)
        write_exact(out/DOCUMENT,encoded(document(value,root_lookup=root_spec)))
        typed=validate_document(out/DOCUMENT,value,root_lookup=root_spec)
        with InputCodec(value['event'],[v.model_dump() for v in typed.source_evidence],native) as codec:
            loaded=backtest.load_repair(out/DOCUMENT,resume_session=cp['source_cursor'],
                predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
            need(loaded.sha256==typed.sha256 and loaded in codec.objects,'BOUNDED_PREPARATION_ACTUAL_INSTALLED_TYPED_PARSER')
            packet=qualify_packets(cp,out/DOCUMENT,loaded,codec,native,value,out)
        hashes=json.loads((HERE/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
        need(len(hashes)==6 and all(cp['base']['sources'].get(n)==h for n,h in hashes.items()),'BOUNDED_PREPARATION_SAME_SIX_CONTROLLER_SOURCES')
        cloud=out/'bounded-sensor-synthetic-cloud';cloud.mkdir();original.qualify(cloud,hashes)
    need(encoded(cp)==before and not any(p.exists() for p in forbidden),'BOUNDED_PREPARATION_ZERO_PARENT_CHANGE_OR_ADOPTION')
    receipt=dict(schema='research.bounded-sensor-zero-transition-preparation/1',passed=True,
        root_admission_sha256=spec['root_admission_sha256'],parent_outer_sha256=cp['sha256'],input_catalog_sha256=CATALOG_SHA,
        typed_document_sha256=typed.sha256,market_source_sha256=sha((out/SOURCE).read_bytes()),
        packet=packet,cloud_qualification_sha256=sha((cloud/'branch-controller-qualification.json').read_bytes()),
        financial_sessions_advanced=0,checkpoint_adopted=False,financial_authority=False,
        portfolio_cash_or_right_price_created=False,old_descriptors_preserved=len(cp['repairs']))
    write_exact(out/QUALIFICATION,encoded(receipt))
    return receipt

def preflight_entry(old,out,spec,legacy,*,enabled=False):
    legacy(old,out,spec)
    if not enabled:return
    from full_system_core import hosted
    hosted()
    import gzip
    need(selected(spec),'BOUNDED_PREPARATION_ENTRY_EXACT_DECLARED_SOURCE_REQUEST')
    cp=json.loads(gzip.decompress((Path(old)/spec['selected_checkpoint']).read_bytes()))
    prepare(cp,out,spec)
