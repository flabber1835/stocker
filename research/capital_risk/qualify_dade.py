"""Future-only fact binding and copy-only canonical DADE payment proof."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from research.pooled_vacancy_funding import backtest,runtime,repair
from research.pooled_vacancy_funding.journal import read_checkpoint
from research.pooled_input_support import inputs
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.terminal import apply_terminal
from suffix_contract import validate_request
from verify_prefix import require,POLICY


@dataclass
class Packet:
    day: str
    terminal: tuple


def qualify(actual,frozen,request,overlay_path):
    validate_request(request)
    spec=request['repair'];p=request['predecessor']
    require(spec['case']=='dade-20071106','REFUSED_UNREVIEWED_REPAIR')
    checkpoint_path=actual/'checkpoint.json.gz';before_file=backtest.file_sha(checkpoint_path)
    saved=read_checkpoint(checkpoint_path)
    require(saved['sha256']==p['outer_sha256'] and saved['source_cursor']=='2007-11-05'
            and saved['repairs']==[],'REFUSED_DADE_PREDECESSOR')
    run=runtime.restore(saved['run'],policy=POLICY,input_sha256=p['input_sha256'])
    require(runtime.checkpoint(run)==saved['run'],'REFUSED_DADE_ROUNDTRIP')
    root=frozen/'historical-repair-evidence/dade-20071106'
    template_path=root/'fixed/overlay.json'
    require(backtest.file_sha(template_path)==spec['template_sha256'],'REFUSED_DADE_FACT_DOCUMENT')
    document=json.loads(template_path.read_bytes())
    sources=[root/'primary-source-extraction.json',
             Path(__file__).parent/'primary-evidence/dade-completion-source-extraction.json']
    require(len(document['source_evidence'])==2,'REFUSED_DADE_SOURCE_COUNT')
    for source,evidence in zip(sources,document['source_evidence']):
        require(backtest.file_sha(source)==evidence['sha256'],'REFUSED_DADE_PRIMARY_EVIDENCE')
    # Bind to THIS actual restored predecessor, never to a copied old identity.
    document['predecessor_checkpoint_sha256']=runtime.checkpoint(run)['checkpoint_sha256']
    raw=(json.dumps(document,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    require(hashlib.sha256(raw).hexdigest()==spec['overlay_sha256'],'REFUSED_DADE_OVERLAY_COMMITMENT')
    overlay_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    require(not overlay_path.exists(),'REFUSED_DADE_OVERLAY_OVERWRITE')
    overlay_path.write_bytes(raw)
    bound=repair.load_repair(overlay_path,resume_session=saved['source_cursor'],
                             predecessor_checkpoint_sha256=saved['run']['checkpoint_sha256'])
    original=tuple(inputs.load_actions(frozen/'bundle').terminal['2007-11-06'])
    packet=Packet('2007-11-06',original);corrected=repair.apply_repair(packet,bound)
    sid=spec['security_id']
    old=[t for t in original if t.security_id==sid];new=[t for t in corrected.terminal if t.security_id==sid]
    require(len(old)==len(new)==1 and not old[0].completeness(0)[0] and new[0].completeness(0)[0]
            and new[0].cash_per_share==77 and new[0].session=='2007-11-06','REFUSED_DADE_FACT_TERMS')
    require([t for t in corrected.terminal if t.security_id!=sid]==[t for t in original if t.security_id!=sid]
            and len(corrected.terminal)==len(original),'REFUSED_DADE_UNRELATED_FACT_CHANGE')
    require(repair.apply_repair(Packet('2007-11-05',()),bound)==Packet('2007-11-05',()),
            'REFUSED_DADE_PREDECESSOR_PACKET_CHANGED')
    for cursor,predecessor in [('2007-11-06',saved['run']['checkpoint_sha256']),('2007-11-05','0'*64)]:
        try:repair.load_repair(overlay_path,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_DADE_BINDING_FALSIFIER')
    core=PortfolioState.from_dict(deepcopy(run.state.wealth_core));ledger=Ledger()
    quantity=sum(e.current_shares for e in core.episodes.values() if e.security_id==sid)
    require(quantity==33,'REFUSED_DADE_FRESH_BASELINE_HOLDING')
    require(not any(e.get('ticker')=='DADE' and e['event_type']=='CASH_MERGER'
                    for e in saved['run']['state']['ledger']['events']),'REFUSED_DADE_ALREADY_PAID')
    cash=core.cash
    applied=apply_terminal(core,new[0],ledger=ledger,session='2007-11-06',cfg=runtime.config(run.policy))
    require(applied['applied'] and abs(core.cash-cash-float(quantity*77))<1e-8
            and not any(e.security_id==sid for e in core.episodes.values()),'REFUSED_DADE_CANONICAL_PAYMENT')
    descriptor=dict(filename=bound.sha256+'.json',sha256=bound.sha256,resume_session=saved['source_cursor'],
                    predecessor_checkpoint_sha256=saved['run']['checkpoint_sha256'])
    require(backtest.input_hash(saved['base'],[descriptor])==request['expected_input_sha256'],
            'REFUSED_DADE_SUCCESSOR_INPUT')
    require(runtime.checkpoint(run)==saved['run'] and backtest.file_sha(checkpoint_path)==before_file,
            'REFUSED_DADE_PROOF_MUTATED_SOURCE_BOOK')
    return dict(schema='research.capital-risk-dade-qualification/1',status='CANONICAL_DADE_QUALIFIED',
        predecessor_outer=saved['sha256'],predecessor_inner=saved['run']['checkpoint_sha256'],
        source_state_unchanged=True,source_files_verified=2,wrong_parent_refused=True,consumed_session_refused=True,
        actual_quantity=str(quantity),canonical_copy_payment=str(quantity*77),copy_position_removed=True,
        overlay_sha256=bound.sha256,successor_input_sha256=request['expected_input_sha256'],
        actual_replay_proof_pending=True,ledger=ledger.to_dict())


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('actual','frozen','request','overlay','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();result=qualify(args.actual,args.frozen,json.loads(args.request.read_bytes()),args.overlay)
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
