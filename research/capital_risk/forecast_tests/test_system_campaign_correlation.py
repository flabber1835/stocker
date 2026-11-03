"""Synthetic sensor arithmetic and causality; no local account/controller replay."""
import ast,copy,hashlib,math,os
from bisect import bisect_left
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from system_campaign_correlation import render,threshold_batch,decode,module
from system_campaign_joint_space import DEFAULT_CORRELATION


def source():
    p=os.environ.get('STOCKER_FROZEN_RESEARCH_SOURCE')
    if not p:pytest.skip('Frozen canonical bytes admitted inside hosted study')
    raw=(Path(p)/'sentinel/controller/median5_breadth.py').read_bytes()
    return raw,hashlib.sha256(raw).hexdigest()


def test_parameterized_canonical_residuals_exclude_current_and_future_closes():
    raw,expected=source();tree=ast.parse(render(raw,DEFAULT_CORRELATION,expected))
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_finite','_residuals','_correlation')]
    def at(series,index):
        if index<0 or series is None:return None
        pos=bisect_left(series.session_indices,index)
        return series.signal_closes[pos] if pos<len(series.session_indices) and series.session_indices[pos]==index else None
    scope={'np':np,'at':at};exec(compile(ast.Module(body=functions,type_ignores=[]),'<synthetic-canonical-residual>','exec'),scope)
    series=SimpleNamespace(session_indices=list(range(271)),signal_closes=[100.+i*.1+math.sin(i)*.5 for i in range(271)])
    market={i:math.cos(i*.3)*.01 for i in range(271)}
    residual=scope['_residuals'](series,270,market)
    assert len(residual)==252 and max(residual)==269
    series.signal_closes[-1]=1.e6;series.session_indices.append(271);series.signal_closes.append(1.e9)
    assert scope['_residuals'](series,270,market)==residual
    assert scope['_correlation']({i:float(i) for i in range(119)},{i:float(i) for i in range(119)}) is None
    assert scope['_correlation']({i:float(i) for i in range(120)},{i:float(i) for i in range(120)})==1.
    with pytest.raises(ValueError,match='FROZEN_SOURCE'):render(raw+b'\n',DEFAULT_CORRELATION,expected)


def test_threshold_batch_preserves_inclusive_damage_unavailable_and_green_escalation():
    held=[SimpleNamespace(own_dd=-.1,r21=.1),SimpleNamespace(own_dd=None,r21=-.03),SimpleNamespace(own_dd=float('nan'),r21=None),SimpleNamespace(own_dd=-.01,r21=.1)]
    stress=np.asarray([[0.,0.,.5,.5],[0.,0.,.49,.8]])
    profiles=[dict(DEFAULT_CORRELATION),{**DEFAULT_CORRELATION,'own_dd':-.15,'r21':-.06,'stress':.67}]
    damage,counts,labels=threshold_batch(held,[False,False,False,True],stress,profiles)
    assert counts.tolist()==[3,0] and damage.tolist()==[.75,0.] and labels[0].tolist()==[True,True,True,False]
    assert decode({'ieee754_binary64':'7ff8000000000000'})!=decode({'ieee754_binary64':'7ff8000000000000'})
    with pytest.raises(ValueError,match='EXPLICIT_NONFINITE_ONLY'):decode({'ieee754_binary64':'3ff0000000000000'})


def test_historical_classifier_entry_requires_hosted_worker(monkeypatch):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED_CORRELATION_ONLY'):module(b'',DEFAULT_CORRELATION,'0'*64)
