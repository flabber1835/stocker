"""Canonical source-startup pause. A transition attempt is always a refusal."""
from copy import deepcopy
from pathlib import Path
import signal
from p01_celg_bridge_gate import need,source_adoption


class SourcePause:
    def __init__(self,old,bridge,event,path):
        self.old=deepcopy(old);self.bridge=deepcopy(bridge);self.event=deepcopy(event)
        self.path=Path(path).resolve();self.saved=None;self.initial_writes=0;self.adoption_writes=0
        self.advance_attempts=0

    def advance(self,*args,**kwargs):
        self.advance_attempts+=1
        raise ValueError('REFUSED_P01_CELG_BRIDGE_ZERO_SOURCE_STARTUP_CANNOT_ADVANCE')

    def write(self,path,saved):
        need(Path(path).resolve()==self.path,'SOURCE_STARTUP_ONLY_DISPOSABLE_CURRENT_CHECKPOINT')
        if saved==self.bridge and self.saved is None:
            need(self.initial_writes==0,'SOURCE_STARTUP_ONE_INITIAL_BRIDGE_WRITE')
            self.initial_writes+=1;return self.original_write(path,saved)
        if self.saved is not None:
            need(saved==self.saved and self.adoption_writes==1,'SOURCE_STARTUP_IDENTICAL_FINAL_FLUSH_ONLY')
            self.adoption_writes+=1;return self.original_write(path,saved)
        source_adoption(saved,self.bridge,self.old,self.event)
        handler=signal.getsignal(signal.SIGTERM)
        need(callable(handler) and getattr(handler,'__code__',None) is not None
             and handler.__code__.co_filename==self.backtest.run_backtest.__code__.co_filename
             and handler.__code__.co_freevars==('stop',),'SOURCE_STARTUP_ACTUAL_CANONICAL_PRIVATE_STOP_HANDLER')
        stop=dict(zip(handler.__code__.co_freevars,handler.__closure__))['stop'].cell_contents
        need(type(stop) is list and not stop,'SOURCE_STARTUP_PRIVATE_STOP_LIST_EMPTY')
        self.original_write(path,saved);handler(signal.SIGTERM,None)
        need(stop==[signal.SIGTERM],'SOURCE_STARTUP_CANONICAL_STOP_REQUESTED_WITHOUT_OS_SIGNAL')
        self.saved=deepcopy(saved);self.adoption_writes=1

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest,runtime
        need(backtest.source_files()==self.bridge['base']['sources'],'SOURCE_STARTUP_EXACT_SUCCESSOR_CANONICAL_SOURCE')
        self.backtest,self.runtime=backtest,runtime
        self.original_write,self.original_advance=backtest.write_checkpoint,runtime.advance
        self.handlers={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
        backtest.write_checkpoint=self.write;runtime.advance=self.advance;return self

    def __exit__(self,*args):
        self.backtest.write_checkpoint=self.original_write;self.runtime.advance=self.original_advance
        for sig,handler in self.handlers.items():signal.signal(sig,handler)

    def proof(self):
        need(self.initial_writes==1 and self.adoption_writes in (1,2)
             and self.advance_attempts==0 and self.saved is not None,'EXACT_ZERO_SESSION_SOURCE_STARTUP')
        return dict(status='OWN475_CANONICAL_SOURCE_STARTUP_QUALIFIED_ZERO_SESSIONS',
            original_outer_sha256=self.old['sha256'],source_checkpoint_sha256=self.saved['sha256'],
            source_inner_sha256=self.saved['run']['checkpoint_sha256'],
            source_state_sha256=self.saved['run']['state_sha256'],source_input_sha256=self.saved['run']['input_sha256'],
            initial_writes=self.initial_writes,adoption_writes=self.adoption_writes,
            attempted_financial_transitions=0,financial_sessions_advanced=0,source_event=self.event,
            reused_old_source_canonical_restore=True,financial_predecessor_authorized=False)
