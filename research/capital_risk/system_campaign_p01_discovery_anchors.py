"""Source-verified historical basis anchors for a diagnostic suffix only."""
import ast
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field
from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_discovery_context import TAINT,digest,encoded

ADAPTER_SHA='4fcb1326b8b9e713837257613330abd33927e940106e1473654958f085c1fc08'
STREAM='retained-anchor-events.jsonl'


class SourceAnchor(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True,allow_inf_nan=False)
    security_id: str
    session: str
    ticker: str
    raw_close: float=Field(gt=0)
    signal_close: float=Field(gt=0)
    origin: Literal['FROZEN_SOURCE_PACKET','CURRENT_WINDOW_INPUT_RING']


def prepare_tree(raw):
    need(hashlib.sha256(raw).hexdigest()==ADAPTER_SHA,'DISCOVERY_ANCHOR_EXACT_FROZEN_INPUT_ADAPTER')
    owner,=[n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='Buffer']
    fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='prepare']
    fn=deepcopy(fn)
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='sid'
            and ast.unparse(n.iter)=='live']
    guard,=[n for n in loop.body if isinstance(n,ast.If) and any(isinstance(v,ast.Constant)
        and v.value=='LIVE_ANCHOR_OUTSIDE_WINDOW: ' for v in ast.walk(n))]
    need(ast.unparse(guard.test)=='ring is None or not anchor or anchor[0] not in axis'
         and len(guard.body)==1 and isinstance(guard.body[0],ast.Raise),
         'DISCOVERY_ANCHOR_ONE_EXACT_EXPIRED_ANCHOR_GUARD')
    guard.body=ast.parse('''anchors[sid]=_retained_source_anchor(self,prior,sid,anchor)
histories[sid]=() if ring is None else ring.canonical(sid,axis,origin,self.index-260,self.index)
continue''').body
    index=fn.body.index(loop)
    fn.body[index:index]=ast.parse('_remember_source_anchors(self,prior,live,axis,origin)').body
    return ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))


def positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


class RetainedAnchors:
    """Never changes the runtime state, current bars or current-window dates."""
    def __init__(self,output,initial_state,*,source_sha256,input_sha256,bindings=None):
        self.output=Path(output);self.initial_state=initial_state
        self.source_sha256=source_sha256;self.input_sha256=input_sha256;self.bindings=bindings
        self.records={};self.targets={};self.active=False;self.stream=None
        self.chain=digest(dict(authority=TAINT,stream=STREAM));self.sequence=0
        self.hash=hashlib.sha256()

    def __enter__(self):
        hosted();need(not self.active,'DISCOVERY_ANCHOR_CONTEXT_NOT_REENTRANT')
        need(all(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
                 for value in (self.source_sha256,self.input_sha256)),
             'DISCOVERY_ANCHOR_EXACT_SOURCE_AND_FROZEN_INPUT_IDENTITIES')
        if self.bindings is None:
            from research.pooled_input_support import adapter
            from stock_strategy_shared.wealth_core.feed import VendorBar
            self.m=SimpleNamespace(adapter=adapter,VendorBar=VendorBar)
        else:self.m=self.bindings
        for sid in self.m.adapter.protected(self.initial_state):
            anchor=self.initial_state.feed.get('series',{}).get(sid,{}).get('signal_basis_anchor')
            need(isinstance(anchor,list) and len(anchor)==3 and positive(anchor[1])
                 and positive(anchor[2]) and anchor[0]<=self.initial_state.last_processed_session,
                 'DISCOVERY_INITIAL_PROTECTED_RETAINED_ANCHOR_REQUIRED')
            self.targets[sid]=anchor[0]
        raw=Path(self.m.adapter.__file__).read_bytes()
        namespace=dict(vars(self.m.adapter),_remember_source_anchors=self.remember,
                       _retained_source_anchor=self.retained)
        exec(compile(prepare_tree(raw),'<diagnostic-retained-frozen-source-anchor-only>','exec'),namespace)
        self.original=self.m.adapter.Buffer.prepare
        self.stream=(self.output/STREAM).open('xb')
        self.m.adapter.Buffer.prepare=namespace['prepare'];self.active=True
        return self

    def observe(self,packet):
        """Called only while reading the unchanged frozen prefix packets."""
        for bar in packet.bars:
            if self.targets.get(bar.security_id)==packet.day:
                need(bar.session==packet.day,'DISCOVERY_SOURCE_ANCHOR_PACKET_DATE')
                self.store(bar,'FROZEN_SOURCE_PACKET')

    def store(self,bar,origin):
        record=SourceAnchor(security_id=bar.security_id,session=bar.session,ticker=bar.ticker,
            raw_close=bar.raw_close,signal_close=bar.signal_close,origin=origin)
        self.records[bar.security_id]=record
        return record

    def remember(self,buffer,prior,live,axis,origin):
        for sid in sorted(live):
            anchor=prior.feed.get('series',{}).get(sid,{}).get('signal_basis_anchor')
            ring=buffer.rings.get(sid)
            if anchor and ring is not None and anchor[0] in axis:
                actual=ring.anchor(sid,anchor[0],axis,origin)
                self.store(actual,'CURRENT_WINDOW_INPUT_RING')

    def retained(self,buffer,prior,sid,anchor):
        need(isinstance(anchor,list) and len(anchor)==3 and positive(anchor[1])
             and positive(anchor[2]),'DISCOVERY_RETAINED_BASIS_REQUIRED_NOT_INVENTED')
        record=self.records.get(sid)
        need(record is not None and record.security_id==sid and record.session==anchor[0]
             and record.raw_close==float(anchor[1]) and record.session<=prior.last_processed_session
             and prior.last_processed_session<buffer.current.day,
             'DISCOVERY_FROZEN_SOURCE_ANCHOR_MATCHES_RETAINED_RAW_BASIS')
        body=dict(schema='research.disposable-source-anchor-retention/1',authority=TAINT,
            sequence=self.sequence,session=buffer.current.day,security_id=sid,
            prior_state_sha256=prior.state_hash,source_sha256=self.source_sha256,
            input_sha256=self.input_sha256,
            source_anchor=record.model_dump(),source_anchor_sha256=digest(record.model_dump()),
            convention='HISTORICAL_BASIS_ONLY_NOT_CURRENT_BAR_MARK_OPEN_FILL_OR_SETTLEMENT')
        self.chain=digest(dict(previous=self.chain,record=body))
        raw=encoded(dict(record=body,chain_sha256=self.chain))+b'\n'
        self.stream.write(raw);self.stream.flush();os.fsync(self.stream.fileno())
        self.hash.update(raw);self.sequence+=1
        return self.m.VendorBar(record.session,sid,record.ticker,record.raw_close,None,None,
                                signal_close=record.signal_close)

    def commitment(self):
        return dict(bytes=self.stream.tell(),prefix_sha256=self.hash.hexdigest(),
                    rows=self.sequence,chain_sha256=self.chain)

    def __exit__(self,*args):
        if self.active:
            self.m.adapter.Buffer.prepare=self.original;self.active=False
        if self.stream is not None:self.stream.close()
