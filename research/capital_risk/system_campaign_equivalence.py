"""Strict differential state/input comparison; no local financial replay entry."""
from collections import deque
from dataclasses import asdict,is_dataclass
import array,hashlib,json,struct,sys
from pathlib import Path
import numpy as np
from full_system_benchmark import need
from system_campaign_compare import rows as financial_rows
from system_campaign_facts import digest


def exact(value):
    """Typed deterministic buffer material; no lossy fallback for unknown types."""
    if value is None or type(value) in (bool,int,str):return value
    if type(value) is float:return {'binary64':struct.pack('>d',value).hex()}
    if isinstance(value,np.generic):return {'numpy_scalar':str(value.dtype),'bytes':value.tobytes().hex()}
    if isinstance(value,np.ndarray):return {'numpy_array':str(value.dtype),'shape':list(value.shape),
        'content_sha256':hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value,array.array):return {'array':value.typecode,'itemsize':value.itemsize,'length':len(value),
        'byteorder':sys.byteorder,'content_sha256':hashlib.sha256(value.tobytes()).hexdigest()}
    if is_dataclass(value):return {'dataclass':type(value).__module__+'.'+type(value).__qualname__,'fields':exact(asdict(value))}
    if isinstance(value,dict):
        need(all(type(k) is str for k in value),'EQUIVALENCE_STRING_MAPPING_KEYS')
        return {k:exact(v) for k,v in sorted(value.items())}
    if type(value) is deque:return {'sequence_type':'deque','maxlen':value.maxlen,'items':[exact(v) for v in value]}
    if type(value) in (list,tuple):return {'sequence_type':type(value).__name__,'items':[exact(v) for v in value]}
    raise ValueError('REFUSED_EQUIVALENCE_UNSUPPORTED_BUFFER_TYPE:'+type(value).__module__+'.'+type(value).__qualname__)


def buffer_material(buffer):
    need(set(vars(buffer))=={'axis','spy','rings','metadata','sectors','index','current'},
         'EQUIVALENCE_COMPLETE_BUFFER_FIELDS')
    material={k:v for k,v in vars(buffer).items() if k!='rings'}
    material['rings']={sid:dict(vars(ring)) for sid,ring in buffer.rings.items()}
    return exact(material)


def compare_buffers(old,new):
    left=buffer_material(old);right=buffer_material(new)
    need(left==right,'EQUIVALENCE_COMPLETE_BUFFER_EXACT')
    return digest(left)


def future_plan(document,cutoff):
    need(set(document)=={'schema','predecessor_checkpoint_sha256','source_evidence','suppress','add'}
         and document['schema']=='terminal-repair/1','EQUIVALENCE_ORDINARY_FUTURE_INPUT_ONLY')
    result={}
    for name in ('suppress','add'):
        rows={}
        for row in document[name]:
            if row['session']<=cutoff:continue
            key=row['session'],row['security_id']
            need(key not in rows,'EQUIVALENCE_UNIQUE_FUTURE_ACTION')
            rows[key]=row
        result[name]=rows
    return result


def compare_future_inputs(old_complete,selected,old,new_document,cutoff,future_documents):
    retained=selected['repairs'];extra=old_complete['repairs'][len(retained):]
    need(len(extra)==len(future_documents)
         and all(type(d.get('resume_session')) is str for d in extra)
         and old['repairs'][:len(retained)]==retained
         and old_complete['repairs'][:len(old['repairs'])]==old['repairs']
         and old['repairs']==retained+[d for d in extra if d['resume_session']<=cutoff]
         ,'EQUIVALENCE_EXACT_OLD_INPUT_SUCCESSOR_AXIS')
    expected={'suppress':{},'add':{}}
    for descriptor,document in zip(extra,future_documents):
        need(descriptor['resume_session']>=selected['source_cursor']
             and document['predecessor_checkpoint_sha256']==descriptor['predecessor_checkpoint_sha256']
             and all(row['session']>descriptor['resume_session'] for name in ('suppress','add') for row in document[name])
             and (descriptor['resume_session']<=cutoff or
                  all(row['session']>cutoff for name in ('suppress','add') for row in document[name])),
             'EQUIVALENCE_OLD_SUCCESSOR_STRICTLY_FUTURE')
        for name,rows in future_plan(document,cutoff).items():
            for key,row in rows.items():
                need(key not in expected[name],'EQUIVALENCE_UNIQUE_OLD_FUTURE_ACTION')
                expected[name][key]=row
    need(future_plan(new_document,cutoff)==expected,'EQUIVALENCE_ALL_FUTURE_ACTION_INPUTS_EXACT')
    return sum(d['resume_session']>cutoff for d in extra)


def compare_cutoff(old,new,old_complete,selected,new_document,cutoff,*,future_documents=()):
    """Prove full recurrence state equality and finite support of new input facts."""
    need(old['source_cursor']==new['source_cursor']==cutoff and old['completed']==new['completed'],
         'EQUIVALENCE_EXACT_CUTOFF_AND_COUNT')
    need(old['base']==new['base']==old_complete['base']==selected['base'],
         'EQUIVALENCE_UNCHANGED_FULL_SOURCE_AND_INPUT_BASE')
    future_count=compare_future_inputs(old_complete,selected,old,new_document,cutoff,future_documents)
    need(new['repairs'][:-1]==selected['repairs'] and len(new['repairs'])==len(selected['repairs'])+1,
         'EQUIVALENCE_EXACT_SINGLE_INPUT_SUCCESSOR')
    need(old['run']['state']==new['run']['state'] and old['run']['state_sha256']==new['run']['state_sha256']
         and all(old['run'][k]==new['run'][k] for k in ('schema','base_main_sha','policy')),
         'EQUIVALENCE_COMPLETE_CANONICAL_STATE_EXACT')
    for name in ('economics','stats','spy_base','retries'):
        need(old[name]==new[name],'EQUIVALENCE_COMPLETE_'+name.upper()+'_EXACT')
    need(new_document['schema']=='terminal-repair/1'
         and new_document['predecessor_checkpoint_sha256']==selected['run']['checkpoint_sha256'],
         'EQUIVALENCE_OWN_INPUT_SUCCESSOR_BOUNDARY')
    changed=new_document['suppress']+new_document['add']
    need(changed and all(selected['source_cursor']<v['session'] for v in changed)
         and any(v['session']<=cutoff for v in changed),'EQUIVALENCE_ACTUAL_BOUNDED_CHANGED_INTERVAL')
    return {'cutoff':cutoff,'canonical_state_sha256':new['run']['state_sha256'],
        'old_complete_checkpoint_sha256':old_complete['sha256'],
        'old_cutoff_checkpoint_sha256':old['sha256'],'new_cutoff_checkpoint_sha256':new['sha256'],
        'identical_future_ordinary_input_successors':future_count,
        'all_remaining_inputs_unchanged_by_finite_date_support':True,
        'complete_recurrence_state_exact':True,'old_physical_lineage_relabelled':False}


def compare_records(old_root,new_root,old_cp,new_cp):
    counts={}
    for name in ('formation','daily','monthly'):
        records=[]
        for root,cp in ((old_root,old_cp),(new_root,new_cp)):
            raw=(root/(name+'.jsonl')).read_bytes()[:cp['journals'][name]['bytes']]
            need(len(raw)==cp['journals'][name]['bytes']
                 and hashlib.sha256(raw).hexdigest()==cp['journals'][name]['prefix_sha256'],
                 'EQUIVALENCE_ACTUAL_COMMITTED_PREFIX')
            records.append([json.loads(v) for v in raw.splitlines()])
        if name=='monthly':need(records[0]==records[1],'EQUIVALENCE_ALL_MONTHLY_ROWS_EXACT')
        else:financial_rows(*records)
        counts[name]=len(records[0])
    return counts
