import ast,copy,hashlib,json
from pathlib import Path
import pytest
from system_campaign_watch_bound import bound_watch
from system_campaign_compare import watch


def data():
    rows=[];preimages=[]
    for identity in ('A','B'):
        document={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':identity,
            'source_evidence':[],'suppress':[],'add':[{'cash':137}]}
        raw=json.dumps(document).encode()
        cp={'base':{'source':'same'},'source_cursor':'day','run':{'checkpoint_sha256':identity,
            'state_sha256':'state','input_sha256':identity+'-input'}}
        row={'schema':'research.pooled-action-successor/1','predecessor_checkpoint_sha256':identity,
            'state_sha256':'state','predecessor_input_sha256':identity+'-input',
            'successor_input_sha256':identity+'-next','unchanged_through':'day',
            'overlay':{'filename':identity+'.json','predecessor_checkpoint_sha256':identity,
                'sha256':hashlib.sha256(raw).hexdigest(),'resume_session':'day'}}
        rows.append([row]);preimages.append((cp,raw))
    return rows,preimages


def test_strict_refusal_retained_and_exact_own_preimages_admitted():
    rows,preimages=data();before=copy.deepcopy(rows)
    with pytest.raises(ValueError,match='OTHER_WATCH'):watch(*rows)
    bound_watch(*rows,lambda row:preimages[0],lambda row:preimages[1]);assert rows==before


@pytest.mark.parametrize('change',('input','raw','economic','date'))
def test_bad_preimage_or_economic_change_refused(change):
    rows,preimages=data()
    if change=='input':preimages[1][0]['run']['input_sha256']='wrong'
    elif change=='raw':preimages[1]=(preimages[1][0],b'wrong')
    elif change=='date':rows[1][0]['unchanged_through']='wrong'
    else:
        doc=json.loads(preimages[1][1]);doc['add'][0]['cash']=138;raw=json.dumps(doc).encode()
        preimages[1]=(preimages[1][0],raw);rows[1][0]['overlay']['sha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):bound_watch(*rows,lambda row:preimages[0],lambda row:preimages[1])


def test_actual_preimage_guard_removal_falsifier():
    rows,preimages=data();preimages[1][0]['run']['input_sha256']='wrong'
    with pytest.raises(ValueError,match='ACTUAL_OWN_PREDECESSOR_INPUT'):bound_watch(*rows,lambda row:preimages[0],lambda row:preimages[1])
    node=next(n for n in ast.parse(Path(bound_watch.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='bound_watch')
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,node):
            if any(isinstance(x,ast.Constant) and x.value=='BOUND_WATCH_ACTUAL_OWN_PREDECESSOR_INPUT' for x in ast.walk(node)):return None
            return self.generic_visit(node)
    node=Remove().visit(node)
    scope=dict(bound_watch.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-actual-input-preimage>','exec'),scope)
    scope['bound_watch'](*rows,lambda row:preimages[0],lambda row:preimages[1])
