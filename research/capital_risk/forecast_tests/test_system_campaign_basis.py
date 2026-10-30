"""A common factual basis cannot conceal different economic terms."""
import ast,copy,hashlib,json
from pathlib import Path
import pytest
from system_campaign_basis import semantics
from system_campaign_facts import digest
import system_campaign_basis as module


def data():
    base={'bundle_sha256':'a'*64,'archive_sha256':'b'*64}
    refs={'facts':'c'*64,'compiler':'d'*64}
    one={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':'1'*64,
        'source_evidence':[{'reference':k,'sha256':v} for k,v in refs.items()],
        'suppress':[],'add':[{'session':'2020-01-02','security_id':'X','cash_per_share':42.}]}
    two={**copy.deepcopy(one),'predecessor_checkpoint_sha256':'2'*64,'add':[]}
    return base,refs,one,two


def test_own_identity_and_descriptor_partition_do_not_change_actual_fact_basis():
    base,refs,one,two=data();actual=semantics(base,[one,two],refs)
    assert actual==semantics(base,[two,one],refs)
    changed=copy.deepcopy(one);changed['predecessor_checkpoint_sha256']='9'*64
    assert actual==semantics(base,[changed],refs)
    changed['add'][0]['cash_per_share']=43.
    assert digest(actual)!=digest(semantics(base,[changed],refs))


def test_missing_reference_conflicting_cash_and_wrong_compiler_refuse():
    base,refs,one,two=data()
    with pytest.raises(ValueError,match='ALL_FACTS_PRESENT'):semantics(base,[],refs)
    two['add']=[{**one['add'][0],'cash_per_share':43.}]
    with pytest.raises(ValueError,match='CONFLICTING_TERM'):semantics(base,[one,two],refs)
    one['source_evidence'][0]['sha256']='0'*64
    with pytest.raises(ValueError,match='DECLARED_FACT_COMPILER'):semantics(base,[one],refs)


def test_actual_compiler_guard_removal_falsifier():
    base,refs,one,two=data();one['source_evidence'][0]['sha256']='0'*64
    with pytest.raises(ValueError,match='DECLARED_FACT_COMPILER'):semantics(base,[one],refs)
    tree=ast.parse(Path(semantics.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='semantics')
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,n):
            if any(isinstance(v,ast.Constant) and v.value=='COMMON_BASIS_DECLARED_FACT_COMPILER' for v in ast.walk(n)):return None
            return self.generic_visit(n)
    node=Remove().visit(node);scope=dict(semantics.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-fact-compiler-guard>','exec'),scope)
    assert scope['semantics'](base,[one],refs)['declared_fact_compilers']['facts']=='0'*64


@pytest.mark.parametrize('removed',('SPRING','LATE','YEAREND','FOLLOWON','PARSLEY','EARLY2019'))
def test_required_hydrations_and_actual_omission_falsifier(tmp_path,monkeypatch,removed):
    driver=tmp_path/'driver';driver.mkdir();evidence=tmp_path/'evidence';evidence.mkdir()
    names={module.CATALOG_REF:driver/'system-campaign-factual-catalog.json',
        module.COMPILER_REF:driver/'system_campaign_facts.py',module.HYDRATED_REF:evidence/'hydrated-factual-catalog.json',
        module.ADDITIONAL:driver/'system-campaign-additional-terminal-facts.json',
        module.ADDITIONAL_COMPILER:driver/'system_campaign_terminal_facts.py',
        module.ADDITIONAL_HYDRATED:evidence/'hydrated-additional-terminal-catalog.json',
        module.WINTER:driver/'system-campaign-corrected-winter-facts.json',
        module.WINTER_COMPILER:driver/'system_campaign_winter_facts.py',
        module.WINTER_HYDRATED:evidence/'hydrated-corrected-winter-cash-catalog.json',
        module.SPRING:driver/'system-campaign-spring-terminal-facts.json',
        module.SPRING_COMPILER:driver/'system_campaign_spring_facts.py',
        module.SPRING_HYDRATED:evidence/'hydrated-spring-terminal-catalog.json',
        module.FOLLOWUP:driver/'system-campaign-followup-terminal-facts.json',
        module.FOLLOWUP_COMPILER:driver/'system_campaign_followup_facts.py',
        module.FOLLOWUP_HYDRATED:evidence/'hydrated-followup-terminal-catalog.json',
        module.TGI:driver/'system-campaign-tgi-cash-facts.json',
        module.TGI_COMPILER:driver/'system_campaign_tgi_facts.py',
        module.TGI_HYDRATED:evidence/'hydrated-tgi-cash-catalog.json',
        module.MIDYEAR:driver/'system-campaign-midyear-terminal-facts.json',
        module.MIDYEAR_COMPILER:driver/'system_campaign_midyear_facts.py',
        module.MIDYEAR_HYDRATED:evidence/'hydrated-midyear-terminal-catalog.json',
        module.LATE:driver/'system-campaign-late-terminal-facts.json',
        module.LATE_COMPILER:driver/'system_campaign_late_facts.py',
        module.LATE_HYDRATED:evidence/'hydrated-late-terminal-catalog.json',
        module.YEAREND:driver/'system-campaign-yearend-terminal-facts.json',
        module.YEAREND_COMPILER:driver/'system_campaign_yearend_facts.py',
        module.YEAREND_HYDRATED:evidence/'hydrated-yearend-terminal-catalog.json',
        module.FOLLOWON:driver/'system-campaign-followon-terminal-facts.json',
        module.FOLLOWON_COMPILER:driver/'system_campaign_followon_facts.py',
        module.FOLLOWON_HYDRATED:evidence/'hydrated-followon-terminal-catalog.json',
        module.PARSLEY:driver/'system-campaign-parsley-terminal-facts.json',
        module.PARSLEY_COMPILER:driver/'system_campaign_parsley_facts.py',
        module.PARSLEY_HYDRATED:evidence/'hydrated-parsley-terminal-catalog.json',
        module.EARLY2019:driver/'system-campaign-early2019-terminal-facts.json',
        module.EARLY2019_COMPILER:driver/'system_campaign_early2019_facts.py',
        module.EARLY2019_HYDRATED:evidence/'hydrated-early2019-terminal-catalog.json'}
    for ref,p in names.items():p.write_bytes(ref.encode())
    refs={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in names.items()}
    document={'schema':'terminal-repair/1','source_evidence':[{'reference':k,'sha256':v} for k,v in refs.items()],
        'suppress':[],'add':[]}
    repair=evidence/'book/repairs/r.json';repair.parent.mkdir(parents=True);repair.write_text(json.dumps(document))
    cp={'base':{'bundle_sha256':'a'*64,'archive_sha256':'b'*64},
        'repairs':[{'filename':'r.json','sha256':hashlib.sha256(repair.read_bytes()).hexdigest()}]}
    def path(value):return driver/Path(value).name if str(value).startswith('/driver/') else Path(value)
    monkeypatch.setattr(module,'Path',path)
    assert set(module.basis(evidence,cp)[1]['declared_fact_compilers'])==set(refs)
    names[getattr(module,removed+'_HYDRATED')].unlink()
    with pytest.raises(ValueError,match='ACTUAL_COMPLETE_FACT_FILES'):module.basis(evidence,cp)
    node=next(n for n in ast.parse(Path(module.basis.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='basis')
    mapping=next(n.value for n in node.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Dict))
    pairs=[(k,v) for k,v in zip(mapping.keys,mapping.values) if not isinstance(k,ast.Name) or not k.id.startswith(removed)]
    mapping.keys=[k for k,v in pairs];mapping.values=[v for k,v in pairs]
    scope=dict(module.basis.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-required-basis-component>','exec'),scope)
    assert getattr(module,removed) not in scope['basis'](evidence,cp)[1]['declared_fact_compilers']
