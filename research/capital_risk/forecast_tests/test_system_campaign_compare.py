"""Pure comparator falsifiers; no historical financial rule execution."""
from copy import deepcopy
import pytest
from system_campaign_compare import rows,origin_state,facts,watch

def test_record_economic_and_unknown_mutations_refuse():
    a={'input_sha256':'a','chain_sha256':'a','state_sha256':'same','economics':{'cash':50},'evidence':{'fee':1}}
    b=deepcopy(a);b.update(input_sha256='b',chain_sha256='b');rows([a],[b])
    for target in ('cash','fee','unknown'):
        c=deepcopy(b)
        if target=='cash':c['economics']['cash']=51
        elif target=='fee':c['evidence']['fee']=2
        else:c['new_field']=None
        with pytest.raises(ValueError):rows([a],[c])

def test_origin_and_factual_nonidentity_fields_are_exact():
    a={'wealth_core':{'median5':{'sums':{'S':[1.,0.,0.,0.,0.,0.,0.]},'rank_history':[]},'cash':50}}
    b=deepcopy(a);b['wealth_core']['median5']['sums']['S'][0]+=1e-15
    assert origin_state(a,b)==1
    b['wealth_core']['cash']=49
    with pytest.raises(ValueError):origin_state(a,b)
    x={'predecessor_checkpoint_sha256':'a','add':[{'cash_per_share':315}]};y=deepcopy(x);y['predecessor_checkpoint_sha256']='b';facts(x,y)
    y['add'][0]['cash_per_share']=314
    with pytest.raises(ValueError):facts(x,y)

def test_watch_requires_exact_economic_successor_details():
    a={'schema':'research.pooled-action-successor/1','predecessor_checkpoint_sha256':'a','state_sha256':'a','successor_input_sha256':'a',
       'unchanged_through':'2017-06-30','overlay':{'filename':'a','predecessor_checkpoint_sha256':'a','sha256':'a','add_count':2}}
    b=deepcopy(a);b['successor_input_sha256']='b';watch([a],[b]);b['overlay']['add_count']=1
    with pytest.raises(ValueError):watch([a],[b])
