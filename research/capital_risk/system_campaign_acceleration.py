"""Verified transaction-local value reuse; no strategy or account equations."""
from dataclasses import fields,is_dataclass
import os,threading,time
from pathlib import Path

def need(value,code):
    if not value:raise ValueError('REFUSED_CAMPAIGN_ACCELERATION_'+code)

class ReadHashScope:
    """Reuse only one prior object's digest, then independently rehash it."""
    def __init__(self,state_type):
        self.state_type=state_type;self.original=state_type.__dict__['state_hash'];self.prior=None
        self.owner=None;self.digest=None;self.hits=0;self.checks=0

    def begin(self,prior):
        need(self.prior is None and self.state_type.__dict__['state_hash'] is self.original,'OVERLAPPING_TRANSACTION')
        need(isinstance(prior,self.state_type),'STATE_TYPE')
        self.digest=self.original.fget(prior);self.prior=prior;self.owner=threading.get_ident()
        scope=self
        def value(instance):
            if instance is scope.prior and threading.get_ident()==scope.owner:
                scope.hits+=1;return scope.digest
            return scope.original.fget(instance)
        self.replacement=property(value);self.state_type.state_hash=self.replacement

    def end(self):
        need(self.prior is not None and self.state_type.__dict__['state_hash'] is self.replacement,'TRANSACTION_OWNERSHIP')
        prior,expected=self.prior,self.digest
        self.state_type.state_hash=self.original;self.prior=None;self.owner=None;self.digest=None
        actual=self.original.fget(prior);self.checks+=1
        need(actual==expected,'NESTED_PRIOR_MUTATION')

def shallow_signal(cls,bar,original):
    if not is_dataclass(bar) or {f.name for f in fields(bar)}!=set(cls.model_fields):return original(cls,bar),False
    def immutable(v):
        return v is None or type(v) in (str,int,float,bool) or isinstance(v,tuple) and all(immutable(x) for x in v)
    value={f.name:getattr(bar,f.name) for f in fields(bar) if f.name!='closes'}
    if not all(immutable(v) for v in value.values()):return original(cls,bar),False
    value['closes']=getattr(bar,'closes')[-1:]
    return cls.model_validate(value),True

class Execution:
    def __init__(self,mode):
        need(mode in ('FAST','REFERENCE'),'MODE');self.mode=mode;self.timings=[];self.signal_fast=0;self.signal_fallback=0

    def __enter__(self):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
            and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_ONLY')
        from research.pooled_input_support.adapter import Buffer
        from research.pooled_vacancy_funding import runtime,backtest
        from sentinel.core.session import SessionState
        from sentinel.core.window_material import Signal
        self.Buffer,self.runtime,self.backtest,self.Signal=Buffer,runtime,backtest,Signal
        self.prepare,self.advance=Buffer.prepare,runtime.advance
        self.signal=Signal.__dict__['from_feature'];self.scope=ReadHashScope(SessionState)
        self.saved={name:getattr(backtest,name) for name in ('checkpoint_value','write_checkpoint')}
        def prepare(buffer,prior,*args,**kwargs):
            start=time.monotonic()
            if self.mode=='FAST':self.scope.begin(prior)
            try:return self.prepare(buffer,prior,*args,**kwargs)
            except BaseException:
                if self.mode=='FAST' and self.scope.prior is not None:self.scope.end()
                raise
            finally:self.timings.append({'stage':'prepare','session':buffer.current.day,'seconds':time.monotonic()-start})
        def advance(run,published):
            start=time.monotonic()
            if self.mode=='FAST':need(self.scope.prior is run.state,'EXACT_PREPARED_PRIOR')
            try:return self.advance(run,published)
            finally:
                if self.mode=='FAST' and self.scope.prior is not None:self.scope.end()
                self.timings.append({'stage':'advance','session':published.session,'seconds':time.monotonic()-start})
        def signal(cls,bar):
            value,used=shallow_signal(cls,bar,self.signal.__func__);self.signal_fast+=int(used);self.signal_fallback+=int(not used);return value
        def timed(name):
            def call(*args,**kwargs):
                start=time.monotonic()
                try:return self.saved[name](*args,**kwargs)
                finally:self.timings.append({'stage':name,'seconds':time.monotonic()-start})
            return call
        Buffer.prepare=prepare;runtime.advance=advance
        if self.mode=='FAST':Signal.from_feature=classmethod(signal)
        for name in self.saved:setattr(backtest,name,timed(name))
        return self

    def __exit__(self,kind,value,tb):
        try:
            if self.scope.prior is not None:self.scope.end()
        finally:
            self.Buffer.prepare=self.prepare;self.runtime.advance=self.advance;self.Signal.from_feature=self.signal
            for name,fn in self.saved.items():setattr(self.backtest,name,fn)

    def proof(self):
        return {'mode':self.mode,'prior_hash_reuses':self.scope.hits,'independent_prior_immutability_checks':self.scope.checks,
            'signal_fast_calls':self.signal_fast,'signal_fallback_calls':self.signal_fallback,'timings':self.timings,
            'validation_verdict_cached':False,'cross_session_state_cache':False,'canonical_financial_equations_changed':False}
