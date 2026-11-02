"""Synthetic-only differential of batching against exact canonical pure kernels."""
import ast,hashlib,math,os,sys,types
from dataclasses import asdict,dataclass
from pathlib import Path
from bisect import bisect_left
from types import SimpleNamespace
from typing import Dict,Optional,Sequence,Tuple
import numpy as np
import pytest
import system_campaign_correlation as batch
from system_campaign_joint_space import correlations,DEFAULT_CORRELATION


def test_synthetic_full_batch_matches_parameterized_canonical_classifier(monkeypatch):
    source=os.environ.get('STOCKER_FROZEN_RESEARCH_SOURCE')
    if not source:pytest.skip('Explicit frozen source location needed for pure-kernel differential')
    source=Path(source);raw=(source/'sentinel/controller/median5_breadth.py').read_bytes()
    expected=hashlib.sha256(raw).hexdigest()
    classifier=ast.parse((source/'sentinel/breadth/classifier.py').read_bytes())
    returns=ast.parse((source/'sentinel/breadth/returns.py').read_bytes())
    allowed={'Holding','HoldingLabel','SessionBreadth','is_green','is_red'}
    definitions=[n for n in classifier.body if isinstance(n,ast.Assign) or
        isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in allowed]
    available=next(n for n in returns.body if isinstance(n,ast.FunctionDef) and n.name=='is_available')
    counter=0
    def pure_module(raw,parameters,expected_sha):
        nonlocal counter
        counter+=1;name='_synthetic_pure_classifier_'+str(counter);module=types.ModuleType(name)
        monkeypatch.setitem(sys.modules,name,module)
        def at(series,index):
            position=bisect_left(series.session_indices,index)
            return series.signal_closes[position] if position<len(series.session_indices) and series.session_indices[position]==index else None
        module.__dict__.update(np=np,math=math,dataclass=dataclass,Optional=Optional,Sequence=Sequence,
            Dict=Dict,Tuple=Tuple,SimpleNamespace=SimpleNamespace,at=at)
        tree=ast.parse(batch.render(raw,parameters,expected_sha))
        kernels=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
        future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
        material=ast.fix_missing_locations(ast.Module(body=[future,available,*definitions,*kernels],type_ignores=[]))
        exec(compile(material,'<synthetic-only-canonical-classifier-kernels>','exec'),module.__dict__)
        return module
    # Only the source-extracted pure classifier kernels see invented test data.
    # No historical module entry, account, controller or Core is executed here.
    monkeypatch.setattr(batch,'module',pure_module)
    registered=correlations();parameters=[r['parameters'] for r in registered]
    base=pure_module(raw,DEFAULT_CORRELATION,expected);held=[]
    for i in range(6):
        holding=base.Holding('FAKE'+str(i),None,[-.1,-.075,None,-.2,-.001,-.01][i],
            [-.03,0.,.05,-.02,-.07,.09][i],[-.1,.01,None,-.02,.02,.01][i],20 if i%2 else 80)
        held.append({'slot':i,'canonical_holding':asdict(holding),'peer_key':['FAKE_ISSUER',str(i)],
            'session_indices':list(range(271)),
            'signal_closes':[100.+d*.02+math.sin(d*.19+i)*2+math.cos(d*.037)*i for d in range(271)]})
    material={'index':270,'held':held,'spy_history':[[d,1000.+d,math.cos(d*.3)*.01] for d in range(271)]}
    material['canonical_breadth']=asdict(base.from_capture(material)[0])
    actual=batch.ClassifierBatch(raw,expected,parameters).one(material)
    assert len(actual['ambers'])==2916 and actual['denominator']==6
    for index in (0,1,10,200,499,900,1200,1800,2300,2600,2800,2915):
        direct=pure_module(raw,parameters[index],expected).from_capture(material)[0]
        assert int(actual['ambers'][index])==direct.ambers and float(actual['damage'][index])==direct.damaged_breadth
