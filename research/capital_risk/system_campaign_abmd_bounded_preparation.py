"""Hosted parser/recalendar/cloud preparation; no checkpoint adoption or transition."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
from system_campaign_abmd_bounded_catalog import validate,encoded,document,evidence
from system_campaign_abmd_bounded_hydration import hydrate
from system_campaign_bounded_sensor_input import InputCodec,parse,need,sha,digest
from system_campaign_bounded_sensor_binding import basis

DOCUMENT='abmd-preparation-input.json'
SOURCE='abmd-preparation-event-source.json'
QUALIFICATION='abmd-zero-transition-preparation.json'

def write_exact(path,raw):
    path=Path(path)
    if path.exists():need(path.read_bytes()==raw,'ABMD_PREPARATION_EXACT_EXISTING_BYTES')
    else:
        with path.open('xb') as stream:stream.write(raw)

def qualify_packets(cp,path,loaded,native,catalog):
    from full_system_core import hosted
    hosted()
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import backtest
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    from system_campaign_sprint_facts import qualify_packet_schema,published_packet
    qualify_packet_schema(Packet,cp['base']['sources']['research/pooled_input_support/adapter.py'])
    event=catalog['event'];source=catalog['market_source'];sid=event['security_id']
    prior=SimpleNamespace(median5=dict(selected=[sid]),wealth_core=dict(episodes={}),pending=[],
        last_processed_session='2022-12-21',feed=dict(series={sid:dict(signal_basis_anchor=('2022-12-21',
        float(source['raw_prior_row']['raw_close']),float(source['raw_prior_row']['signal_close'])))}))
    checks=0;range_=None
    for day in ('2022-12-21','2022-12-22'):
        bar=vendor(source['raw_prior_row']) if day=='2022-12-21' else None
        original=Packet(day,(bar,) if bar else (),{},{},1.,{},(native,) if day=='2022-12-21' else (),())
        before=asdict(original);fixed=backtest.apply_repair(original,loaded);expected=deepcopy(before)
        expected['terminal']=() if day=='2022-12-21' else (dict(asdict(native),session='2022-12-22'),)
        need(asdict(original)==before and asdict(fixed)==expected,'ABMD_PREPARATION_ONLY_TERMINAL_RECALENDAR_NATIVE_BAR_PRESERVED')
        if day=='2022-12-22':
            published=published_packet(fixed)
            need(published.bars==[] or published.bars==(),'ABMD_PREPARATION_NO_FABRICATED_COMPLETION_BAR')
            try:terminal_returns.values(prior=prior,published=published)
            except ValueError as error:
                need(str(error).startswith('incomplete leadership cash terminal:'),'ABMD_PREPARATION_ORIGINAL_INCOMPLETE_GUARD_REASON')
            else:raise ValueError('ABMD_PREPARATION_ORIGINAL_INCOMPLETE_GUARD_MISSING')
            selected,range_=basis(prior,published,event,source,native)
            need(selected['selected'] is True and range_==[380.,415.],'ABMD_PREPARATION_COMPLETE_LEGAL_SIGNAL_RANGE')
            absent=deepcopy(prior);absent.median5['selected']=[]
            point,interval=basis(absent,published,event,source,native)
            need(point['selected'] is False and interval is None,'ABMD_PREPARATION_UNSELECTED_HAS_NO_RIGHT_VALUE')
        checks+=1
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),('2022-12-21',cp['run']['checkpoint_sha256'])):
        try:backtest.load_repair(path,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('ABMD_PREPARATION_PARSER_FALSIFIER_ACCEPTED')
    return dict(actual_packet_checks=checks,actual_selected_signal_range=range_,unselected_has_no_right_value=True,
        native_day_bar_preserved=True,effective_day_quote_absent=True,original_incomplete_guard_retained=True,
        wrong_predecessor_and_consumed_native_cursor_refused=True,no_financial_transition=True)

def prepare(cp,out,spec,*,catalog_path,catalog_sha256):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_partial import root_spec
    from system_campaign_bounded_sensor_preparation import no_financial_transitions
    from research.pooled_vacancy_funding import backtest
    import system_campaign_financial_branches as original
    raw=Path(catalog_path).read_bytes();need(sha(raw)==catalog_sha256,'ABMD_PREPARATION_EXACT_REQUESTED_CATALOG')
    catalog=validate(json.loads(raw),root_lookup=root_spec);out=Path(out)
    need(spec['arm']==catalog['arm'] and spec['root_admission_sha256']==catalog['parent_root_admission_sha256']
         and (cp['sha256'],cp['source_cursor'],cp['completed'])==(catalog['parent_outer_sha256'],catalog['parent_cursor'],catalog['parent_completed'])
         and cp['repairs']==catalog['parent_descriptors'],'ABMD_PREPARATION_EXACT_CURRENT_OWN_FULL_PARENT')
    forbidden=(out/'book/checkpoint.json.gz',out/'input-adoption/checkpoint.json.gz')
    need(not any(p.exists() for p in forbidden),'ABMD_PREPARATION_NO_CREATED_CHECKPOINT_AT_START')
    before=encoded(cp)
    with no_financial_transitions():
        native,source=hydrate(catalog,out/SOURCE);write_exact(out/DOCUMENT,encoded(document(catalog)))
        typed=parse(out/DOCUMENT,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
                    expected_event=catalog['event'],expected_evidence=evidence(catalog))
        with InputCodec(catalog['event'],evidence(catalog),native) as codec:
            loaded=backtest.load_repair(out/DOCUMENT,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
            need(loaded in codec.objects and loaded.sha256==typed.sha256,'ABMD_PREPARATION_INSTALLED_TYPED_PARSER')
            packets=qualify_packets(cp,out/DOCUMENT,loaded,native,catalog)
        hashes=json.loads((Path(__file__).parent/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
        need(len(hashes)==6 and all(cp['base']['sources'].get(n)==h for n,h in hashes.items()),'ABMD_PREPARATION_SIX_FROZEN_CONTROLLER_SOURCES')
        folder=out/'abmd-synthetic-cloud';folder.mkdir();original.qualify(folder,hashes)
    need(encoded(cp)==before and not any(p.exists() for p in forbidden),'ABMD_PREPARATION_ZERO_PARENT_CHANGE_NO_ADOPTION')
    receipt=dict(schema='research.abmd-zero-transition-parser-packet-cloud-preparation/1',passed=True,arm=catalog['arm'],
        root_admission_sha256=spec['root_admission_sha256'],parent_outer_sha256=cp['sha256'],catalog_sha256=catalog_sha256,
        document_sha256=typed.sha256,market_source_sha256=sha((out/SOURCE).read_bytes()),packets=packets,
        cloud_qualification_sha256=sha((folder/'branch-controller-qualification.json').read_bytes()),
        old_descriptors_preserved=len(cp['repairs']),financial_sessions_advanced=0,checkpoint_adopted=False,
        financial_authority=False,cash_or_right_price_created=False)
    write_exact(out/QUALIFICATION,encoded(receipt));return receipt
