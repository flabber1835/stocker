"""Training-only joint selection with one official cross-Core risk benchmark."""
import math
from datetime import date
from fractions import Fraction as Q
from system_campaign_facts import digest
from system_campaign_joint_space import joint_profiles
from system_campaign_space import record
from full_system_benchmark import need

METRIC_KEYS={'anchor','start','end','closes','initial_nav','nav','multiple','total_return','cagr',
    'maximum_drawdown_magnitude','measured_closes'}
CUTOFFS=('2020-12-31','2022-12-30')


def metric(value,cutoff,axis=None):
    need(set(value)==METRIC_KEYS and value['end']==cutoff and value['anchor']=='2018-01-02'
         and value['start']=='2018-01-03' and type(value['closes']) is int
         and type(value['measured_closes']) is int and value['closes']+1==value['measured_closes'],
         'JOINT_SELECTION_TRAINING_METRIC_ONLY')
    need(Q(value['initial_nav'])==50000 and Q(value['nav'])>0 and Q(value['multiple'])>0
         and Q(value['nav'])/Q(value['initial_nav'])==Q(value['multiple'])
         and Q(value['total_return'])==Q(value['multiple'])-1
         and 0<=Q(value['maximum_drawdown_magnitude'])<1 and math.isfinite(value['cagr']),
         'JOINT_SELECTION_VALID_METRIC')
    days=(date.fromisoformat(cutoff)-date.fromisoformat(value['anchor'])).days
    need(abs(value['cagr']-math.expm1(math.log(float(Q(value['multiple'])))*365.2425/days))<1e-12,
         'JOINT_SELECTION_GROWTH_CONSISTENCY')
    if axis is not None:
        need(all(value[k]==axis[k] for k in ('anchor','start','end','closes','measured_closes')),
             'JOINT_SELECTION_COMMON_TRAINING_AXIS')


def assemble(envelopes,cutoff,baseline_core_id,expected_core_ids,baseline_equivalence_sha256):
    need(cutoff in CUTOFFS and len(baseline_equivalence_sha256)==64,'JOINT_SELECTION_FROZEN_SCOPE')
    registry=joint_profiles();ids=[v['id'] for v in registry['joint_profiles']];baseline_joint=registry['baseline_id']
    need(len({v['core_id'] for v in envelopes})==len(envelopes),'JOINT_SELECTION_UNIQUE_CORE_PATHS')
    admitted=[];ineligible=[];common=None;parameters={}
    for envelope in envelopes:
        need(set(envelope)=={'core_id','parameters','available_after','common_factual_basis_sha256',
            'numeric_review_sha256','training'},'JOINT_SELECTION_NO_EVALUATION_ENVELOPE')
        core=envelope['core_id'];need(record(envelope['parameters'])['id']==core,'JOINT_SELECTION_CORE_PARAMETER_ID')
        need(envelope['available_after'] in ('INITIAL',*CUTOFFS),'JOINT_SELECTION_DECLARED_AVAILABILITY')
        need(len(envelope['numeric_review_sha256'])==64 and len(envelope['common_factual_basis_sha256'])==64,
             'JOINT_SELECTION_ACTUAL_REVIEW_AND_FACT_BINDINGS')
        document=envelope['training']
        need(set(document)=={'cutoff','records','core_profile_sha256','no_evaluation_fields'}
             and document['cutoff']==cutoff and document['no_evaluation_fields'] is True
             and document['core_profile_sha256']==digest(envelope['parameters'])
             and [r['id'] for r in document['records']]==ids,'JOINT_SELECTION_COMPLETE_FINITE_JOINT_CLASS')
        if envelope['available_after']!='INITIAL' and envelope['available_after']>cutoff:
            ineligible.append(core);continue
        need(core in expected_core_ids,'JOINT_SELECTION_EXPECTED_CHRONOLOGICAL_CORE')
        if common is None:common=envelope['common_factual_basis_sha256']
        need(common==envelope['common_factual_basis_sha256'],'JOINT_SELECTION_UNIFORM_FACTS')
        parameters[core]=envelope['parameters']
        for row in document['records']:
            need(set(row)=={'id','group','metrics','turnover'} and Q(row['turnover'])>=0,
                 'JOINT_SELECTION_TRAINING_ROW_ONLY')
            metric(row['metrics'],cutoff)
            admitted.append({'id':core+'::'+row['id'],'core_id':core,'joint_id':row['id'],
                'group':core+'::'+row['group'],'metrics':row['metrics'],'turnover':row['turnover']})
    baseline_id=baseline_core_id+'::'+baseline_joint
    by={v['id']:v for v in admitted};need(baseline_id in by,'JOINT_SELECTION_OFFICIAL_BASELINE_PRESENT')
    base=by[baseline_id]
    for row in admitted:metric(row['metrics'],cutoff,base['metrics'])
    return admitted,base,{'common_factual_basis_sha256':common,'baseline_equivalence_sha256':baseline_equivalence_sha256,
        'parameters':parameters,'missing_core_ids':sorted(set(expected_core_ids)-set(parameters)-set(ineligible)),
        'later_only_core_ids_excluded':sorted(ineligible)}


def lock(records,base,cutoff,scope):
    """Exact constrained growth ranking; unknown coverage is never scored zero."""
    need(records and cutoff in CUTOFFS and base in records,'JOINT_SELECTION_NONEMPTY_TRAINING_CLASS')
    for row in records:
        need(set(row)=={'id','core_id','joint_id','group','metrics','turnover'} and Q(row['turnover'])>=0,
             'JOINT_LOCK_TRAINING_ROW_ONLY')
        metric(row['metrics'],cutoff,base['metrics'])
    draw=Q(base['metrics']['maximum_drawdown_magnitude']);chosen=[];budgets=[]
    def order(row):return (-Q(row['metrics']['multiple']),Q(row['turnover']),row['id']!=base['id'],row['id'])
    for fraction in ('0.50','0.75','1.0'):
        limit=draw*Q(fraction);allowed=[r for r in records if Q(r['metrics']['maximum_drawdown_magnitude'])<=limit]
        winner=min(allowed,key=order) if allowed else None
        budgets.append({'relative_budget':fraction,'absolute_drawdown_budget':str(limit),'id':winner['id'] if winner else None})
        if winner:chosen.append(winner['id'])
    joint=[r for r in records if Q(r['metrics']['multiple'])>Q(base['metrics']['multiple'])
        and Q(r['metrics']['maximum_drawdown_magnitude'])<draw]
    best=min(joint,key=order) if joint else None
    if best:chosen.append(best['id'])
    document={'schema':'research.system-campaign-global-training-lock/1','cutoff':cutoff,
        'status':'TRAINING_LOCKED' if not scope['missing_core_ids'] else 'PARTIAL_CLASS_TRAINING_LOCKED_UNKNOWN_COVERAGE_RETAINED',
        'selected':list(dict.fromkeys(chosen)),'baseline_id':base['id'],'budget_choices':budgets,
        'training_joint_improvements':len(joint),'best_training_joint':best['id'] if best else None,
        'reviewed_joint_configurations':len(records),'scope':scope,'evaluation_used':False,'global_optimum_claim':False}
    return {**document,'sha256':digest(document)}


def acquisition_records(records,base,cutoff,parameters,*,initial_ids):
    """Only initial training objective scalars enter compute allocation."""
    need(cutoff in CUTOFFS and base in records,'JOINT_ACQUISITION_TRAINING_ONLY')
    need(set(parameters)<=set(initial_ids),'JOINT_ACQUISITION_INITIAL_ONLY')
    for row in records:metric(row['metrics'],cutoff,base['metrics'])
    draw=float(Q(base['metrics']['maximum_drawdown_magnitude']));result=[]
    def objective(row,budget):
        value=row['metrics'];days=(date.fromisoformat(value['end'])-date.fromisoformat(value['anchor'])).days
        growth=math.log(float(Q(value['multiple'])))*365.2425/days;dd=float(Q(value['maximum_drawdown_magnitude']))
        return growth-4*max(0.,dd-budget*draw),growth,dd
    for core,p in sorted(parameters.items()):
        own=[r for r in records if r['core_id']==core];need(own,'JOINT_ACTUAL_CORE_TRAINING_SCORES')
        rows=[]
        for budget in (.5,.75,1.):
            winner=min(own,key=lambda r:(-objective(r,budget)[0],Q(r['turnover']),r['id']))
            _,growth,dd=objective(winner,budget)
            rows.append({'relative_budget':budget,'annual_log_growth':growth,'drawdown_magnitude':dd,
                'baseline_drawdown_magnitude':draw})
        result.append({'core_id':core,'training_end':cutoff,'parameters':p,'budgets':rows})
    return result
