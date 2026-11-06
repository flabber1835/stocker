"""Noncanonical observer metadata DTOs cover the real original constructor."""
import json
from copy import deepcopy
from pathlib import PurePosixPath
import pytest
import system_campaign_pending_cash_api as api
import system_campaign_qualified_pending_cash as cash

class Member:
    def __init__(self,values,name=''):self.values,self.name=values,name
    def __truediv__(self,name):return Member(self.values,(PurePosixPath(self.name)/name).as_posix())
    def read_bytes(self):return self.values[self.name]

def metadata():
    # This has no state/schema/commitment and is not a canonical checkpoint.
    cp=dict(sha256=cash.OUTER,source_cursor='2022-06-30',completed=1132,repairs=['SYNTHETIC']*15)
    _,_,terms=api.private_api().selected('P05',cursor='2022-06-30')
    material=dict(arm='P05',terms=terms)
    values={api.original.OVERLAY:cash.encoded(dict(add=[t['added'] for t in terms])),
            api.original.hydration_name(cp):cash.encoded(material)}
    return cp,material,values

def test_original_constructor_code_with_private_scope_binding_resolves_new_phase():
    cp,material,values=metadata();Original=api.original.ActualEvents
    constructor=api.observer_initializer(Original.__init__,cp,'P05')
    assert constructor.__code__ is Original.__init__.__code__
    assert constructor.__globals__['source_scopes'].__code__ is api.original.source_scopes.__code__
    observer=object.__new__(Original);constructor(observer,Member(values),'P05',cp=cp)
    assert observer.scopes==[] and observer.terms=={('2022-07-01',cash.SID):material['terms'][0]['added']}
    assert observer.advance.__func__ is Original.advance and observer.terminal.__func__ is Original.terminal

def test_unbound_original_constructor_reproduces_FIN319_missing_selector():
    cp,_,values=metadata();Original=api.original.ActualEvents;observer=object.__new__(Original)
    with pytest.raises(KeyError,match='P05'):Original.__init__(observer,Member(values),'P05',cp=cp)

def test_source_only_reclassification_is_still_refused_by_entire_original_scope_guard():
    cp,material,values=metadata();material=deepcopy(material)
    material['terms'][0]['recognition_rule']=api.original.SOURCE_CLOSE
    values[api.original.hydration_name(cp)]=cash.encoded(material)
    constructor=api.observer_initializer(api.original.ActualEvents.__init__,cp,'P05')
    with pytest.raises(ValueError,match='SOURCE_ONLY_SCOPE_CANNOT_BE_OMITTED_OR_RECLASSIFIED'):
        constructor(object.__new__(api.original.ActualEvents),Member(values),'P05',cp=cp)

def test_other_phases_keep_identical_constructor_and_foreign_constructor_refuses():
    original=api.original.ActualEvents.__init__
    assert api.observer_initializer(original,None,'P05') is original
    assert api.observer_initializer(original,dict(source_cursor='2022-05-31'),'P05') is original
    cp,_,_=metadata()
    with pytest.raises(ValueError,match='EXACT_ORIGINAL_OBSERVER_CONSTRUCTOR'):
        api.observer_initializer(lambda *a,**k:None,cp,'P05')
