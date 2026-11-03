"""Hydrate original eleven codecs before resuming the admitted OWN627 epoch."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import gzip
import json
from pathlib import Path

from p01_native_resume_parent import (OUTER,SOURCE_RECEIPT,TENTH,ELEVENTH,sha,digest,need,validate_contents)
from p01_epoch_resume import _quote,_source_files


def _hosted():
    from full_system_core import hosted
    hosted()


def _source_module():
    from research.pooled_vacancy_funding import source_successor
    return source_successor


class NativeEpochSourceGate:
    """Only unchanged admitted627 startup; no source or input adoption operation."""
    def __init__(self,parent,source_map,receipt_path,checkpoint_path):
        need(parent['sha256']==OUTER and parent['base']['sources']==source_map['successor_financial_sources'],
             'GATE_EXACT_ADMITTED627_EPOCH')
        self.parent=deepcopy(parent);self.base=deepcopy(parent['base'])
        self.receipt_path=Path(receipt_path);self.checkpoint_path=Path(checkpoint_path);self.loads=0

    def load(self,path,current_base):
        raw=Path(path).read_bytes();receipt=json.loads(raw)
        if receipt.get('schema')!='research.p01-celg-own475-source-successor/1':
            return self.original_load(path,current_base)
        need(Path(path).resolve()==self.receipt_path.resolve() and sha(raw)==SOURCE_RECEIPT,
             'EXACT_EXISTING_ARCHIVED150A2_RECEIPT')
        need({**current_base,'source_successor_sha256':SOURCE_RECEIPT}==self.base
             and ('source_successor_sha256' not in current_base or current_base['source_successor_sha256']==SOURCE_RECEIPT),
             'IDENTICAL_CURRENT_SOURCE_POLICY_AND_INPUT_BASE')
        saved=json.loads(gzip.decompress(self.checkpoint_path.read_bytes()))
        need(saved==self.parent and saved['sha256']==OUTER
             and saved['sha256']==digest({k:v for k,v in saved.items() if k!='sha256'})
             and saved['run']['input_sha256']==digest(dict(base=self.base,repairs=saved['repairs'])),
             'ONLY_ACTUAL627_NO_RELABELED_PARENT_OR_NEW_INPUT')
        self.loads+=1
        return deepcopy(self.base),None

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
    source_gate:NativeEpochSourceGate
    source_receipt_path:Path

    @property
    def source_args(self):return ['--source-successor',str(self.source_receipt_path)]


@contextmanager
def historical_epoch(old,out,spec,*,quote_root=Path('/celg-input'),
        quote_descriptor_path=Path('/celg-input-descriptor.json'),checkpoint_path=None):
    _hosted();old,out=Path(old),Path(out)
    parent=validate_contents(old,spec)
    mapping=json.loads((old/'source-map.json').read_bytes())
    need(_source_files()==mapping['successor_all_sources'],'EXACT516_ACTUAL_SOURCE_BEFORE_QUOTE_OR_RESTORE')
    quote,descriptor=_quote(quote_root,quote_descriptor_path)
    from p01_celg_bridge_run import old_inputs,native
    from p01_celg_bridge_codec import InputCodec as CelgCodec,OLD,SID
    from p01_factual_batch_codec import InputCodec as BatchCodec,source_terms
    from research.pooled_vacancy_funding import backtest
    tenth=(old/'book/repairs'/parent['repairs'][9]['filename']).read_bytes()
    eleventh=(old/'book/repairs'/parent['repairs'][10]['filename']).read_bytes()
    need(sha(tenth)==TENTH and sha(eleventh)==ELEVENTH,'EXACT_ORIGINAL_TENTH_AND_ELEVENTH_RAW_BYTES')
    document=json.loads(tenth)
    need(document['quote_capsule']==descriptor and document['terms']['right_quote']==quote
         and document['quote_input_sha256']==digest(quote),'ORIGINAL_HISTORICAL_QUOTE_BINDING')
    receipt_path=old/'source-successor.json';checkpoint_path=checkpoint_path or out/'book/checkpoint.json.gz'
    # These frozen contexts authenticate/hydrate old inputs only; never restore a book.
    with old_inputs(old,{**parent,'repairs':parent['repairs'][:9]},out/'contexts'), \
         CelgCodec(native(OLD,SID),document) as celg, BatchCodec(source_terms()) as batch:
        objects=[]
        for d in parent['repairs']:
            obj=backtest.load_repair(old/'book/repairs'/d['filename'],resume_session=d['resume_session'],
                predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
            need(obj.sha256==d['sha256'],'ELEVEN_ARCHIVED_CODECS_ORIGINAL_ORDER_BEFORE_RESTORE');objects.append(obj)
        need(len(objects)==11 and any(objects[9] is x for x in celg.objects)
             and any(objects[10] is x for x in batch.objects),'ACTUAL_TENTH_AND_ELEVENTH_OBJECT_REGISTRATION')
        with NativeEpochSourceGate(parent,mapping,receipt_path,checkpoint_path) as gate:
            yield HistoricalEpoch(deepcopy(parent),deepcopy(mapping),deepcopy(quote),deepcopy(descriptor),
                                  tuple(objects),gate,receipt_path)
