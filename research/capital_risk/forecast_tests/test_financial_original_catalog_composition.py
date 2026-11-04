"""One original catalog may supply disjoint future cash and delivery terms."""
import ast
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_partial as p


def test_own232_and_original_late_terms_preserve_exact_source_bytes():
    root=p.root_spec('P05');assert root['measured_closes']==232
    cash,name,terms=f.original_ordinary_selection('P05','2018-11-30')
    delivery,other,mixed=f.original_delivery_selection('P05','2018-11-30')
    assert name==other=='system-campaign-late-terminal-facts.json'
    assert cash.catalog_sha==delivery.catalog_sha=='0db4e7eb49ab973bbb6f7bb9579e2a33776b2f7ead3fe25f9cb40812cb3efca7'
    assert cash.compiler_sha==delivery.compiler_sha=='ac77d968aee0ffc769bfba22e69ca16daa5bac6c723997fc947a0612596236ca'
    assert [t['ticker'] for t in terms]==['APTI','VSM'] and [t['ticker'] for t in mixed]==['OCLR']
    assert mixed[0]['added']['cash_per_share']==5.6 and mixed[0]['added']['exchange_ratio']==.0636
    assert mixed[0]['added']['session']=='2018-12-10' and mixed[0]['added']['delivered_ticker']=='LITE'


def test_actual_hydration_composition_keeps_both_kinds_and_one_source_component(tmp_path):
    cash,catalog,terms=f.original_ordinary_selection('P05','2018-11-30')
    tree=ast.parse(Path(f.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='hydrate')
    start=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='delivery' for t in n.targets))
    nodes=fn.body[start:start+2]
    assert isinstance(nodes[1],ast.If) and ast.unparse(nodes[1].test)=='delivery is not None'
    scope=dict(vars(f),arm='P05',cp=dict(source_cursor='2018-11-30',repairs=[]),source_root=tmp_path,
        ordinary=(cash,catalog,deepcopy(terms)),catalog=catalog,terms=deepcopy(terms),
        ordinary_components=[deepcopy(cash.ordinary_source)],inherited_ordinary=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<actual-source-only-hydration-composition>','exec'),scope)
    assert [t['ticker'] for t in scope['terms']]==['APTI','VSM','OCLR']
    assert scope['ordinary_components']==[cash.ordinary_source] and scope['inherited_ordinary']==[]


def test_p03_own125_uses_original_midyear_cash_and_delivery_from_its_new_admitted_root():
    root=p.root_spec('P03','70ebc8c3f1378bf7b18a84326bdb172fc5bdd120c9e24b6feb8dbc9f01293002')
    assert (root['measured_closes'],root['selected_session'])==(125,'2018-06-29')
    cash,name,terms=f.selected('P03',cursor=root['selected_session'])
    delivery,other,mixed=f.original_delivery_selection('P03',root['selected_session'])
    assert name==other=='system-campaign-midyear-terminal-facts.json'
    assert cash.catalog_sha==delivery.catalog_sha=='f2467de7dd56d1b69bac24be9caeeedd6be946e1e898dce9a9afefe054437018'
    term,=terms;stock,=mixed
    assert (term['ticker'],term['native_session'],term['added']['session'],term['added']['cash_per_share'])==('FMI','2018-07-31','2018-07-31',137.)
    assert stock['ticker']=='COL' and stock['added']['session']=='2018-11-27'
    merged=f.merge_selected_terms(terms,mixed)
    assert len(f.suppressions(dict(source_cursor=root['selected_session']),merged))==2
