"""Hosted canonical sensor calls over explicit synthetic metadata; no book transition."""
from copy import deepcopy
from dataclasses import dataclass,replace
from tempfile import TemporaryFile
from types import SimpleNamespace
import json
from system_campaign_bounded_sensor_input import need,sha,digest
from system_campaign_abmd_bounded_catalog import encoded,SID

@dataclass(frozen=True)
class SyntheticPublication:
    session:str
    bars:tuple
    terminal_events:tuple

def qualify(out,catalog,codec,native,hashes,*,inherited_root):
    from full_system_core import hosted
    hosted()
    from sentinel.controller import median5,champion_config,terminal_returns
    from system_campaign_p06_abmd_initial_certificate import certificate_class
    from system_campaign_bounded_sensor_preparation import no_financial_transitions
    from system_campaign_financial_branches import SCHEMA,WATCH,encoded as compact
    cls=certificate_class(catalog['event'],catalog['market_source'],codec,native,inherited_root=inherited_root)
    results=[]
    with no_financial_transitions():
        for selected in (True,False):
            certificate=cls(out,codec,native,hashes,event_source=catalog['market_source'])
            certificate.original_values=terminal_returns.values
            certificate.original_witness=median5.witness;certificate.original_recover=champion_config.recover
            calls=[]
            certificate.original_append=lambda journal,name,record:calls.append((name,deepcopy(record)))
            state=median5.fresh(champion=True)
            names=([SID] if selected else [])+['SYNTHETIC_OTHER']
            state.update(last_session='2022-12-21',witness_nav=[1.02**n for n in range(41)],selected=names,
                selected_closes={sid:381.02 if sid==SID else 100. for sid in names})
            prior=SimpleNamespace(not_canonical_state=True,median5=state,wealth_core=dict(episodes={}),pending=[],
                last_processed_session='2022-12-21',feed=dict(series={SID:dict(signal_basis_anchor=('2022-12-21',381.02,381.02))}))
            publication=SyntheticPublication('2022-12-22',(),(replace(native,session='2022-12-22'),))
            terms=certificate.values(prior=prior,published=publication)
            need((SID in terms)==selected and (certificate.event_bounds is not None)==selected,
                 'P06_GATEWAY_SELECTED_RANGE_OR_UNSELECTED_POINT_ONLY')
            after,observed=certificate.witness(state,session='2022-12-22',candidates=[SimpleNamespace(security_id='SYNTHETIC_OTHER',recent=.02)],
                closes={'SYNTHETIC_OTHER':102.},terminals=(SID,),terminal_values=terms)
            actual,decision=certificate.recover(state=after,native=1.,wc_drawdown=-.05,
                recent_r20=observed['recent_r20'],recent_r40=observed['recent_r40'],spy_r20=.02,wc_r20=.01)
            need(certificate.pending['session']=='2022-12-22' and certificate.pending['bounded_event_basis']['selected']==selected
                 and certificate.pending['event_basis']==certificate.pending['bounded_event_basis']
                 and decision==dict(desired_allocation=1.,reason='NORMAL'),'P06_GATEWAY_ACTUAL_INITIAL_CLOUD_AND_BASIS')
            certificate.pending.update(input_sha256='a'*64,prior_state_sha256='b'*64,next_state_sha256='c'*64)
            with TemporaryFile(mode='w+b',dir=out) as stream:
                certificate.stream=stream
                certificate.append(object(),'daily',dict(session='2022-12-22',input_sha256='a'*64,state_sha256='c'*64))
                stream.seek(0);proof=json.loads(stream.read())
            need(proof['schema']==SCHEMA and proof['chain_sha256']==certificate.chain and certificate.rows==1
                 and [name for name,row in calls]==['watch','daily'] and calls[0][1]['schema']==WATCH
                 and calls[0][1]['certificate_chain_sha256']==proof['chain_sha256'] and certificate.pending is None,
                 'P06_GATEWAY_WHOLE_ORIGINAL_APPEND_CHAIN_AND_WATCH')
            results.append(dict(selected=selected,legal_range=[380.,415.] if selected else None,
                synthetic_proof_sha256=sha(compact(proof)),possible_states=len(proof['possible_after']),
                branches=len(proof['branches']),actual_canonical_sensor_calls=True,whole_original_append=True))
    receipt=dict(schema='research.p06-abmd-initial-synthetic-gateway/1',passed=True,
        synthetic_metadata_only=True,actual_financial_state_used=False,financial_sessions_advanced=0,
        checkpoint_created=False,prior_seed_created=False,source_event_sha256=digest(catalog['market_source']),cases=results)
    (out/'p06-abmd-initial-synthetic-gateway.json').write_bytes(encoded(receipt));return receipt
