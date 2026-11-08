"""Hydrate all eleven historical codecs before exact OWN628 epoch restoration."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import ast
import gzip
import json
from pathlib import Path
import re

from p01_iac_unit_parent import (OUTER,STATE,INPUT,SOURCE_RECEIPT,TENTH,ELEVENTH,
    sha,digest,need,validate_contents)
from p01_epoch_resume import _quote,_source_files,_adoption

HYDRATOR_SOURCE='5e18fe9f0e68720743e67023fe7e1fbb902ce33e93d0c6eeebd19aa0f6746af6'


def _hosted():
    from full_system_core import hosted
    hosted()


def _source_module():
    from research.pooled_vacancy_funding import source_successor
    return source_successor


def _checkpoint(path):return json.loads(gzip.decompress(Path(path).read_bytes()))


class IacEpochSourceGate:
    """Exact admitted628 plus one canonical input-zero; no source boundary."""
    def __init__(self,parent,source_map,receipt_path,checkpoint_path):
        need(parent['sha256']==OUTER and parent['completed']==628
             and parent['source_cursor']=='2020-06-30' and len(parent['repairs'])==11
             and parent['base']['sources']==source_map['successor_financial_sources']
             and parent['run']['state_sha256']==STATE and parent['run']['input_sha256']==INPUT,
             'GATE_EXACT_ROOT_ADMITTED628_SOURCE_AND_INPUT_EPOCH')
        self.parent=deepcopy(parent);self.base=deepcopy(parent['base'])
        self.receipt_path=Path(receipt_path);self.checkpoint_path=Path(checkpoint_path)
        self.allowed={OUTER:deepcopy(parent)};self.loads=0;self.input_registered=False

    def load(self,path,current_base):
        raw=Path(path).read_bytes();receipt=json.loads(raw)
        if receipt.get('schema')!='research.p01-celg-own475-source-successor/1':
            return self.original_load(path,current_base)
        need(Path(path).resolve()==self.receipt_path.resolve() and sha(raw)==SOURCE_RECEIPT,
             'EXACT_ARCHIVED_SOURCE_RECEIPT_NO_NEW_SOURCE_ADOPTION')
        need({**current_base,'source_successor_sha256':SOURCE_RECEIPT}==self.base
             and ('source_successor_sha256' not in current_base
                  or current_base['source_successor_sha256']==SOURCE_RECEIPT),
             'IDENTICAL_CURRENT516_POLICY_SOURCE_AND_INPUT_BASE')
        saved=_checkpoint(self.checkpoint_path)
        need(saved['sha256'] in self.allowed and saved==self.allowed[saved['sha256']]
             and saved['base']==self.base
             and saved['sha256']==digest({k:v for k,v in saved.items() if k!='sha256'})
             and saved['run']['input_sha256']==digest(dict(base=self.base,repairs=saved['repairs'])),
             'ONLY_EXACT_ADMITTED628_OR_REGISTERED_TWELFTH_INPUT_ZERO')
        self.loads+=1
        return deepcopy(self.base),None

    def allow_input(self,saved,overlay_sha256,earliest):
        need(not self.input_registered and type(overlay_sha256) is str
             and re.fullmatch('[0-9a-f]{64}',overlay_sha256) is not None
             and earliest=='2020-07-01' and saved['source_cursor']=='2020-06-30'
             and type(saved['completed']) is int and saved['completed']==628
             and saved['base']==self.base and len(saved['repairs'])==12
             and saved['repairs'][:-1]==self.parent['repairs']
             and saved['repairs'][-1]['sha256']==overlay_sha256,
             'ONE_EXACT_OWN628_FUTURE_TWELFTH_INPUT_ZERO')
        event=_adoption(saved,self.parent,overlay_sha256,earliest)
        need(saved['run']['state']==self.parent['run']['state']
             and saved['run']['state_sha256']==STATE
             and saved['sha256']==digest({k:v for k,v in saved.items() if k!='sha256'})
             and _checkpoint(self.checkpoint_path)==saved,
             'ACTUAL_CURRENT_FILE_AND_ENTIRE_SESSIONSTATE_UNCHANGED_AT_INPUT_ZERO')
        self.allowed[saved['sha256']]=deepcopy(saved);self.input_registered=True
        return event

    def __enter__(self):
        _hosted();self.module=_source_module();self.original_load=self.module.load_successor
        self.module.load_successor=self.load;return self

    def __exit__(self,*args):self.module.load_successor=self.original_load


@dataclass(frozen=True)
class HistoricalEpoch:
    parent:dict
    source_map:dict
    quote:dict
    descriptor:dict
    objects:tuple
    source_gate:IacEpochSourceGate
    source_receipt_path:Path

    @property
    def source_args(self):return ['--source-successor',str(self.source_receipt_path)]


def historical_epoch(old,out,spec,*,quote_root=Path('/celg-input'),
        quote_descriptor_path=Path('/celg-input-descriptor.json'),checkpoint_path=None):
    """Reuse the frozen eleven-codec hydrator with this exact new epoch gate."""
    import p01_native_resume_epoch as previous
    raw=Path(previous.__file__).read_bytes()
    need(sha(raw)==HYDRATOR_SOURCE,'FROZEN_ELEVEN_CODEC_HYDRATION_FUNCTION_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='historical_epoch']
    namespace=dict(vars(previous),**{k:v for k,v in globals().items() if not k.startswith('__')},
                   NativeEpochSourceGate=IacEpochSourceGate)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<source-bound-own628-historical-hydration>','exec'),namespace)
    return namespace['historical_epoch'](old,out,spec,quote_root=quote_root,
        quote_descriptor_path=quote_descriptor_path,checkpoint_path=checkpoint_path)
