"""Prepare a state envelope from actual committed records; no account advancement."""
import hashlib,json
from weighted_screen import Screen,digest
from weighted_policy import need

def resume_prefix(prior,contract,rows,descriptor):
    raw=(prior/'screen/daily.jsonl').read_bytes()
    need(len(raw)==descriptor['prefix_bytes'] and hashlib.sha256(raw).hexdigest()==descriptor['prefix_sha256'],
        'REFUSED_R_ACTUAL_PREFIX_BYTES')
    samples=[json.loads(x) for x in raw.splitlines()]
    need(len(samples)==descriptor['committed_records']==2 and samples[-1]['session']==descriptor['last_session'],
        'REFUSED_R_ACTUAL_PREFIX_AXIS')
    actual=[r for r in rows if r['phase']=='MEASURED'];chain='0'*64
    for i,record in enumerate(samples):
        need(record['session']==actual[i]['session'] and record['B_economics']==actual[i]['economics'],
            'REFUSED_R_PREFIX_BASELINE')
        for k in ('state','input','chain'):
            need(record['baseline_'+k+'_sha256']==actual[i][k+'_sha256'],'REFUSED_R_PREFIX_SOURCE')
        chain=digest(dict(previous=chain,record={k:v for k,v in record.items() if k!='screen_chain_sha256'}))
        need(chain==record['screen_chain_sha256'],'REFUSED_R_ACTUAL_PREFIX_CHAIN')
    last=samples[-1]
    value=dict(schema='research.capital-weighted-account-state/1',contract=contract,risk=last['risk'],
        accounts=dict(B=last['B_economics'],R=last['R_economics']),completed=len(samples),chain=chain)
    saved={**value,'checkpoint_sha256':digest(value)};engine=Screen.restore(saved,contract)
    need(engine.checkpoint()==saved and actual[len(samples)]['session']==descriptor['next_session'],
        'REFUSED_R_PREFIX_RESTORE_ADJACENCY')
    return engine,samples,raw,saved
