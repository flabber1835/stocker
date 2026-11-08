"""Pause unchanged canonical epoch startup after its normal verified resume."""
from copy import deepcopy
from pathlib import Path
import signal
from p01_factual_batch_contract import need


class EpochPause:
    def __init__(self,parent,path):
        self.parent=deepcopy(parent);self.path=Path(path).resolve();self.writes=0;self.attempts=0

    def advance(self,*args,**kwargs):
        self.attempts+=1
        raise ValueError('REFUSED_P01_FACTUAL_BATCH_EPOCH_ZERO_CANNOT_ADVANCE')

    def write(self,path,saved):
        need(Path(path).resolve()==self.path and saved==self.parent,
             'EPOCH_ZERO_CURRENT_CHECKPOINT_ENTIRELY_UNCHANGED')
        need(self.writes<3,'EPOCH_ZERO_ONLY_NORMAL_STARTUP_AND_FINAL_PAUSE_WRITES')
        self.original_write(path,saved);self.writes+=1
        if self.writes==2:
            handler=signal.getsignal(signal.SIGTERM)
            need(callable(handler) and getattr(handler,'__code__',None) is not None
                 and handler.__code__.co_filename==self.backtest.run_backtest.__code__.co_filename
                 and handler.__code__.co_freevars==('stop',),'EPOCH_ZERO_ACTUAL_PRIVATE_CANONICAL_STOP_HANDLER')
            stop=dict(zip(handler.__code__.co_freevars,handler.__closure__))['stop'].cell_contents
            need(type(stop) is list and not stop,'EPOCH_ZERO_STOP_LIST_EMPTY')
            handler(signal.SIGTERM,None)
            need(stop==[signal.SIGTERM],'EPOCH_ZERO_CANONICAL_PAUSE_WITHOUT_OS_SIGNAL')

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest,runtime
        need(backtest.source_files()==self.parent['base']['sources'],'EPOCH_ZERO_SAME224_CANONICAL_SOURCE')
        self.backtest,self.runtime=backtest,runtime
        self.original_write,self.original_advance=backtest.write_checkpoint,runtime.advance
        self.handlers={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
        backtest.write_checkpoint=self.write;runtime.advance=self.advance;return self

    def __exit__(self,*args):
        self.backtest.write_checkpoint=self.original_write;self.runtime.advance=self.original_advance
        for s,h in self.handlers.items():signal.signal(s,h)

    def proof(self):
        need(self.writes==3 and self.attempts==0,'ACTUAL_UNCHANGED_EPOCH_ZERO_STARTUP')
        return dict(status='OWN526_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS',
            outer_sha256=self.parent['sha256'],inner_sha256=self.parent['run']['checkpoint_sha256'],
            state_sha256=self.parent['run']['state_sha256'],input_sha256=self.parent['run']['input_sha256'],
            checkpoint_writes=self.writes,financial_sessions_advanced=0,attempted_financial_transitions=0,
            full_checkpoint_and_journals_unchanged=True,source_boundary_reemitted=False,
            financial_predecessor_authorized=False)
