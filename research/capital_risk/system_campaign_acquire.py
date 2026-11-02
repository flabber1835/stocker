"""Training-objective surrogate for compute allocation, never market forecasts."""
import math
import numpy as np
from system_campaign_space import coordinates,canonical,digest,distance,record

BUDGETS=(.50,.75,1.)
def need(value,code):
    if not value:raise ValueError('REFUSED_CAMPAIGN_ACQUISITION_'+code)
def kernel(x,y):
    x,y=np.asarray(x,float),np.asarray(y,float)
    return np.exp(-np.mean((x[:,None,:]-y[None,:,:])**2,axis=2)/(2*.5**2))
def expected_improvement(mean,sigma,best):
    improvement=mean-best-.01
    if sigma<=0:return max(improvement,0.)
    z=improvement/sigma;cdf=.5*math.erfc(-z/math.sqrt(2));pdf=math.exp(-z*z/2)/math.sqrt(2*math.pi)
    return improvement*cdf+sigma*pdf
def choose(training,universe,initial_ids,cutoff,*,count=4):
    need(cutoff in ('2020-12-31','2022-12-30') and count==4,'FROZEN_CUTOFF_AND_BATCH')
    need(len({r['id'] for r in universe})==len(universe),'UNIQUE_PROPOSALS')
    need(all(r==record(r['parameters']) for r in universe),'PROPOSAL_PARAMETER_IDENTITY')
    initial_ids=set(initial_ids)
    for row in training:
        need(set(row)=={'core_id','training_end','parameters','budgets'} and row['core_id'] in initial_ids
            and row['training_end']==cutoff,'INITIAL_ONLY_CHRONOLOGICAL_INTERFACE')
        need(len(row['budgets'])==3,'COMPLETE_BUDGET_OBJECTIVES')
        need(canonical(row['parameters'])==row['parameters'],'CANONICAL_PARAMETERS')
        need(record(row['parameters'])['id']==row['core_id'],'OBSERVED_PARAMETER_IDENTITY')
        for b,r in zip(BUDGETS,row['budgets']):
            need(set(r)=={'relative_budget','annual_log_growth','drawdown_magnitude','baseline_drawdown_magnitude'}
                and r['relative_budget']==b and all(math.isfinite(r[k]) for k in r)
                and 0<=r['drawdown_magnitude']<1 and 0<=r['baseline_drawdown_magnitude']<1,'TRAINING_METRIC_SHAPE')
    need(len({r['core_id'] for r in training})==len(training),'UNIQUE_ACTUAL_OBSERVATIONS')
    choices=[];proofs=[]
    for index in range(count):
        available=[r for r in universe if r['id'] not in initial_ids and r['id'] not in {c['id'] for c in choices}]
        need(available,'UNCOMPUTED_CANDIDATE_REMAINS');budget_index=index%3
        if not training:
            anchors=[r['parameters'] for r in choices] or [universe[0]['parameters']]
            choice=min(available,key=lambda r:(-min(distance(r['parameters'],p) for p in anchors),r['id']))
            choices.append(choice);proofs.append({'method':'NO_SCORES_MAXIMIN','id':choice['id']});continue
        x=np.asarray([coordinates(r['parameters']) for r in training]);scores=[]
        for r in training:
            b=r['budgets'][budget_index]
            scores.append(b['annual_log_growth']-4*max(0.,b['drawdown_magnitude']-BUDGETS[budget_index]*b['baseline_drawdown_magnitude']))
        y=np.asarray(scores);center=float(y.mean());scale=float(y.std()) or 1.;z=(y-center)/scale;actual_best=float(z.max())
        # Condition only for diversity on posterior means, not invented returns.
        for chosen in choices:
            previous=np.asarray([coordinates(chosen['parameters'])]);k=kernel(x,x)+np.eye(len(x))*1e-6
            chol=np.linalg.cholesky(k);alpha=np.linalg.solve(chol.T,np.linalg.solve(chol,z))
            mean=(kernel(previous,x)@alpha).item();x=np.vstack((x,previous));z=np.append(z,mean)
        covariance=kernel(x,x)+np.eye(len(x))*1e-6;chol=np.linalg.cholesky(covariance)
        alpha=np.linalg.solve(chol.T,np.linalg.solve(chol,z));candidate_x=np.asarray([coordinates(r['parameters']) for r in available])
        cross=kernel(candidate_x,x);mean=cross@alpha;solved=np.linalg.solve(chol,cross.T)
        variance=np.maximum(0.,1.-np.sum(solved*solved,axis=0));sigma=np.sqrt(variance)
        acquisition=[expected_improvement(float(m),float(s),actual_best) for m,s in zip(mean,sigma)]
        selected=min(range(len(available)),key=lambda i:(-acquisition[i],available[i]['id']));choice=available[selected];choices.append(choice)
        proofs.append({'method':'INITIAL_TRAINING_RBF_BATCH_EXPECTED_IMPROVEMENT','relative_budget':BUDGETS[budget_index],
            'id':choice['id'],'training_end':cutoff,'training_core_ids':[r['core_id'] for r in training],
            'real_scores':scores,'score_center':center,'score_scale':scale,'conditioned_coordinates':x.tolist(),
            'conditioned_standardized_values':z.tolist(),'available_ids':[r['id'] for r in available],
            'posterior_mean':mean.tolist(),'posterior_variance':variance.tolist(),'acquisition':acquisition})
    return {'schema':'research.system-campaign-acquisition/1','cutoff':cutoff,'choices':choices,'proofs':proofs,
        'financial_predictions_reported':False,'evaluation_used':False,'global_optimum_claim':False}
