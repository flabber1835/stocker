"""UNSELECTED exact derived market-buffer reconstruction, hosted qualification only."""
from dataclasses import fields,is_dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
import hashlib,json,struct,sys
from pathlib import Path
from pydantic import BaseModel
from full_system_benchmark import need
from full_system_core import hosted


def plan(axis,cursor):
    need(type(axis) is list and axis==sorted(set(axis)) and cursor in axis,
         'RESUME_WINDOW_EXACT_FULL_FINANCIAL_AXIS')
    index=axis.index(cursor)
    need(index>=299 and index+1<len(axis),'RESUME_WINDOW_COMPLETE_WINDOW_AND_NEXT_SESSION')
    return dict(schema='research.exact-derived-buffer-plan/2',original_first=axis[0],
        first=axis[index-299],cursor=cursor,next_session=axis[index+1],last=axis[-1],
        initial_index=index-300,checkpoint_index=index,window=axis[index-299:index+1])


def source_contract(raw,expected_sha256):
    import ast
    need(hashlib.sha256(raw).hexdigest()==expected_sha256,'RESUME_WINDOW_EXACT_PINNED_INPUT_SOURCE')
    tree=ast.parse(raw);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='packets']
    need(len(nodes)==1 and not nodes[0].decorator_list
         and [n.arg for n in nodes[0].args.args]==['bundle','archive_path']
         and [n.arg for n in nodes[0].args.kwonlyargs]==['first','last'],
         'RESUME_WINDOW_EXISTING_CANONICAL_BOUNDED_GENERATOR')
    return hashlib.sha256(raw).hexdigest()


def plain(value):
    if value is None or type(value) in (str,int,bool):return value
    if type(value) is float:return {'binary64':struct.pack('>d',value).hex()}
    if isinstance(value,Enum):return {'enum':type(value).__module__+'.'+type(value).__qualname__,'value':plain(value.value)}
    if isinstance(value,Decimal):return {'Decimal':str(value)}
    if isinstance(value,Fraction):return {'Fraction':[value.numerator,value.denominator]}
    if isinstance(value,(list,tuple)):return {'type':type(value).__name__,'items':[plain(v) for v in value]}
    if isinstance(value,dict):
        need(all(type(k) in (str,int) for k in value),'RESUME_WINDOW_TYPED_MAPPING_KEYS')
        return {'mapping':[[plain(k),plain(value[k])] for k in sorted(value,key=lambda k:(type(k).__name__,str(k)))]}
    tag=type(value).__module__+'.'+type(value).__qualname__
    if is_dataclass(value):return {'dataclass':tag,'fields':[[f.name,plain(getattr(value,f.name))] for f in fields(value)]}
    if isinstance(value,BaseModel):return {'model':tag,'fields':plain(value.model_dump(mode='python'))}
    raise ValueError('REFUSED_RESUME_WINDOW_UNKNOWN_BUFFER_VALUE_TYPE:'+tag)


def exact_buffer(buffer):
    hosted()
    from research.pooled_input_support.adapter import Buffer,Ring
    need(type(buffer) is Buffer and set(vars(buffer))=={'axis','spy','rings','metadata','sectors','index','current'},
         'RESUME_WINDOW_EXACT_CANONICAL_BUFFER_FIELDS')
    need(len(buffer.axis)==len(buffer.spy)==300 and buffer.index>=299
         and buffer.current.day==buffer.axis[-1],'RESUME_WINDOW_FULL_300_SESSION_BUFFER')
    rings={}
    for sid,ring in buffer.rings.items():
        need(type(ring) is Ring and set(vars(ring))=={'indices','tickers','tradeable','values'}
             and set(ring.values)=={'signal_close','raw_close','raw_open','volume','split_ratio','dividend_per_share'},
             'RESUME_WINDOW_EXACT_CANONICAL_RING_FIELDS')
        need(ring.indices and min(ring.indices)>=buffer.index-299 and max(ring.indices)<=buffer.index,
             'RESUME_WINDOW_EXACT_ABSOLUTE_RING_RANGE')
        rings[sid]=dict(indices_typecode=ring.indices.typecode,absolute_indices_bytes=ring.indices.tobytes().hex(),
            tickers=plain(ring.tickers),tradeable_typecode=ring.tradeable.typecode,
            tradeable_bytes=ring.tradeable.tobytes().hex(),
            values={k:dict(typecode=v.typecode,bytes=v.tobytes().hex()) for k,v in sorted(ring.values.items())})
    return dict(schema='research.exact-derived-buffer-representation/2',absolute_index=buffer.index,
        axis=list(buffer.axis),spy=plain(list(buffer.spy)),rings=rings,metadata=plain(buffer.metadata),
        sectors=plain(buffer.sectors),current=plain(buffer.current),byteorder=sys.byteorder)


def compare(cold,bounded):
    hosted();left,right=exact_buffer(cold),exact_buffer(bounded)
    need(left==right,'RESUME_WINDOW_EVERY_EXACT_ABSOLUTE_BUFFER_FIELD')
    raw=json.dumps(left,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return dict(schema='research.exact-derived-buffer-comparison/2',status='EXACT_BUFFER_FIELDS_EQUAL',
        absolute_index=cold.index,representation_sha256=hashlib.sha256(raw).hexdigest(),source_sessions=300,
        index_normalization=False,financial_state_read_or_modified=False,production_contacted=False)


class Reconstruction:
    """Unselected hook: qualify on hosted disjoint probes before any admission."""
    def __init__(self,axis,cursor,*,input_source_sha256,adapter_source_sha256):
        self.plan=plan(axis,cursor);self.expected_input=input_source_sha256
        self.expected_adapter=adapter_source_sha256;self.iterators=0;self.buffers=0

    def __enter__(self):
        hosted()
        from research.pooled_input_support import inputs,adapter
        source_contract(Path(inputs.__file__).read_bytes(),self.expected_input)
        need(hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest()==self.expected_adapter,
             'RESUME_WINDOW_EXACT_PINNED_BUFFER_SOURCE')
        self.inputs=inputs;self.Buffer=adapter.Buffer
        self.original_packets=inputs.packets;self.original_init=adapter.Buffer.__init__
        def packets(bundle,archive_path,*,first=None,last=None):
            need(first==self.plan['original_first'] and last==self.plan['last'] and self.iterators==0,
                 'RESUME_WINDOW_ONE_EXPECTED_FULL_AXIS_ITERATOR')
            self.iterators+=1
            return self.original_packets(bundle,archive_path,first=self.plan['first'],last=last)
        def initialize(buffer):
            need(self.buffers==0,'RESUME_WINDOW_ONE_EXPECTED_DERIVED_BUFFER')
            self.buffers+=1;self.original_init(buffer)
            need(buffer.index==-1 and not buffer.axis and not buffer.rings,'RESUME_WINDOW_FRESH_DERIVED_BUFFER_ONLY')
            buffer.index=self.plan['initial_index']
        inputs.packets=packets;adapter.Buffer.__init__=initialize
        return self

    def __exit__(self,kind,error,traceback):
        self.inputs.packets=self.original_packets;self.Buffer.__init__=self.original_init
        if error is None:need(self.iterators==self.buffers==1,'RESUME_WINDOW_EXACT_HOOK_CALL_COUNTS')
        return False
