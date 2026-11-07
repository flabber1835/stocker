"""Hosted training-only locks and predeclared further compute allocation."""
import argparse,json
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_numeric import hosted
from system_campaign_selection import CUTOFFS,assemble,lock,acquisition_records
from system_campaign_acquire import choose
from system_campaign_space import DEFAULT,initial,record,universe


def select(admitted,out):
    hosted();need(not out.exists(),'GLOBAL_SELECTION_OUTPUT_EXISTS')
    need(set(admitted)=={'schema','baseline_equivalence_sha256','expected_core_ids','cores'}
         and admitted['schema']=='research.system-campaign-admitted-training/1',
         'GLOBAL_SELECTION_TRAINING_ONLY_ADMISSION')
    official=record(DEFAULT)['id'];initial_ids=[v['id'] for v in initial()]
    need(set(initial_ids)<=set(admitted['expected_core_ids'])
         and len(set(admitted['expected_core_ids']))==len(admitted['expected_core_ids'])<=20,
         'GLOBAL_SELECTION_FROZEN_CORE_BUDGET')
    cores=admitted['cores'];envelopes={c:[] for c in CUTOFFS}
    for core in cores:
        need(set(core)=={'core_id','parameters','available_after','common_factual_basis_sha256','numeric_review_sha256','training'}
             and set(core['training'])==set(CUTOFFS),'GLOBAL_SELECTION_ONLY_TWO_TRAINING_DOCUMENTS')
        for cutoff in CUTOFFS:
            envelopes[cutoff].append({**core,'training':core['training'][cutoff]})
    out.mkdir();locks=[];acquisitions=[]
    for cutoff in CUTOFFS:
        rows,baseline,scope=assemble(envelopes[cutoff],cutoff,official,admitted['expected_core_ids'],admitted['baseline_equivalence_sha256'])
        locked=lock(rows,baseline,cutoff,scope);locks.append(locked)
        parameters={k:v for k,v in scope['parameters'].items() if k in initial_ids}
        scores=acquisition_records([r for r in rows if r['core_id'] in parameters],baseline,cutoff,parameters,initial_ids=initial_ids)
        proposed=choose(scores,universe(),initial_ids,cutoff)
        save(out/('training-lock-'+cutoff+'.json'),locked)
        save(out/('acquisition-'+cutoff+'.json'),proposed);acquisitions.append(proposed)
    save(out/'training-locks.json',locks)
    save(out/'selection-summary.json',{'status':'TRAINING_LOCKED_DIRECT_FINALIST_CONFIRMATION_REQUIRED',
        'cutoffs':list(CUTOFFS),'admitted_core_ids':[c['core_id'] for c in cores],
        'unknown_core_ids_by_cutoff':{v['cutoff']:v['scope']['missing_core_ids'] for v in locks},
        'selected':{v['cutoff']:v['selected'] for v in locks},
        'further_compute_choices':{v['cutoff']:[r['id'] for r in v['choices']] for v in acquisitions},
        'evaluation_used':False,'new_core_financial_sessions':0,'global_optimum_claim':False,'production_contacted':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--admitted',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();select(json.loads(a.admitted.read_bytes()),a.output)
