"""Whole SOURCE v1 preparation with authenticated inherited-chain allowance."""
import gzip,json
from pathlib import Path
from types import FunctionType
import system_campaign_p05_remaining_source_preparation as original
import system_campaign_p05_batch_runtime as chain

HERE=Path(__file__).parent
V1_SHA='b703f44d56d4b83d093b30a43806724a6451b966665fa5f48814d2cfe5ac4d0e'
FIELD,PROOF,MODE=original.FIELD,original.PROOF,original.MODE
need,sha=original.need,original.sha
validate_spec,declaration,selected_request=original.validate_spec,original.declaration,original.selected_request
stage_provider,preflight_worker_old=original.stage_provider,original.preflight_worker_old

def source_names():
    return tuple(sorted(set((Path(__file__).name,'P05-retained18-source-preparation-qualification.json',*original.source_names()))))

def inherited(root,spec):
    root=Path(root);validate_spec(spec)
    raw=(root/spec['selected_checkpoint']).read_bytes()
    need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'],'P05_SOURCE18_V2_EXACT_ACTUAL_PARENT_BEFORE_OLD_CHAIN_ALLOWANCE')
    parent=chain.strict_json(raw);original.data.own.parent_contract(parent)
    value=json.loads((root/chain.CHAIN).read_bytes())
    chain.chain_relations(value,parent,lambda n:(root/n).read_bytes())
    allowed={n:pin for n,pin in value['resources'].items() if Path(n).name in ('checkpoint.json.gz','proof.json')}
    for descriptor in parent['repairs']:
        name='book/repairs/'+descriptor['filename'];raw=(root/name).read_bytes()
        need(descriptor['filename']==descriptor['sha256']+'.json' and sha(raw)==descriptor['sha256'],
            'P05_SOURCE18_V2_ALL19_EXACT_AUTHENTIC_ORIGINAL_REPAIR_INPUT_DOCUMENTS')
        allowed[name]=dict(bytes=len(raw),sha256=sha(raw))
    return allowed

def output_members(names,member,allowed):
    neutral={n for n in allowed if n.startswith(('p05-batch-01-adoption/','p05-batch-02-adoption/','p05-batch-03-adoption/'))
        and Path(n).name in ('checkpoint.json.gz','proof.json')}
    repairs={n for n,pin in allowed.items() if n=='book/repairs/'+pin['sha256']+'.json'}
    need(len(neutral)==6 and len(repairs)==19 and set(allowed)==neutral|repairs,
        'P05_SOURCE18_V2_ONLY_SIX_OLD_NEUTRAL_AND19_COMMITTED_INPUT_NAMES')
    need(set(allowed)<=set(names),'P05_SOURCE18_V2_NO_OMISSION_OF_INHERITED_CHAIN_METADATA')
    for name in names:
        canonical=name.split('/')[0] in ('book','input-adoption') or Path(name).name in ('checkpoint.json.gz','proof.json')
        if not canonical:continue
        need(name in allowed,'P05_SOURCE18_NO_NEW_CANONICAL_BOOK_CHECKPOINT_OR_ADOPTION')
        raw=member(name)
        need(dict(bytes=len(raw),sha256=sha(raw))==allowed[name],'P05_SOURCE18_V2_EXACT_INHERITED_CANONICAL_LOOKING_BYTES')
    return sorted(names)

def prepare_after_preflight(old,out,spec):
    original.batch.original.hosted()
    raw=(HERE/'P05-retained18-source-preparation-qualification.json').read_bytes()
    need(sha(raw)==V1_SHA,'P05_SOURCE18_V2_ENTIRE_CLOSED_V1_PREPARATION_QUALIFICATION')
    q=json.loads(raw)
    name=Path(original.__file__).name
    need(q['files'][name]==dict(bytes=Path(original.__file__).stat().st_size,sha256=sha(Path(original.__file__).read_bytes())),
        'P05_SOURCE18_V2_WHOLE_CLOSED_ORIGINAL_SOURCE_PREPARATION_BYTES')
    allowed=inherited(old,spec)
    def reject(root):
        root=Path(root)
        return output_members(original.file_members(root),lambda n:(root/n).read_bytes(),allowed)
    fn=original.prepare_after_preflight
    need(fn.__closure__ is None,'P05_SOURCE18_V2_NO_HIDDEN_PREPARATION_CLOSURE')
    bound=FunctionType(fn.__code__,dict(fn.__globals__,reject_canonical_output=reject),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=fn.__kwdefaults__
    need(bound.__code__ is fn.__code__,'P05_SOURCE18_V2_ENTIRE_ORIGINAL_PREPARATION_FUNCTION')
    return bound(old,out,spec)

def expected_request(*a,**k):
    fn=original.expected_request
    bound=FunctionType(fn.__code__,dict(fn.__globals__,source_names=source_names),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=fn.__kwdefaults__
    return bound(*a,**k)

def bind_preflight(fn):
    namespace=dict(original.bind_preflight.__globals__,prepare_after_preflight=prepare_after_preflight)
    bound=FunctionType(original.bind_preflight.__code__,namespace,original.bind_preflight.__name__,original.bind_preflight.__defaults__)
    return bound(fn)

def bind_launch(*a,**k):return original.bind_launch(*a,**k)
