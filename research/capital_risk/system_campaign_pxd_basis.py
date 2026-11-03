"""Eight actual input parsers and one appended factual/guarded scope."""
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_completion_basis import merge_semantics
from system_campaign_pxd_scope import SCHEMA, SCOPE, parse
from system_campaign_pxd_facts import contract, evidence, expected_repair
import system_campaign_close_basis as previous


def cloned(fn,**bindings):
    need(fn.__closure__ is None,'PXD_BASIS_NO_UNDECLARED_COMPOSITION_CLOSURE')
    result=FunctionType(fn.__code__,dict(fn.__globals__,**bindings),fn.__name__,fn.__defaults__)
    result.__kwdefaults__=fn.__kwdefaults__
    return result


def sources():
    value=contract()
    need(sha(Path(previous.__file__).read_bytes())
         ==value['inherited_sources']['system_campaign_close_basis.py'],
         'PXD_BASIS_EXACT_ADOPTED_SEVEN_MODEL_COMPOSITION')
    return value


def documents(root,cp):
    sources();present=[]
    for descriptor in cp['repairs']:
        need(descriptor['filename']==descriptor['sha256']+'.json'
             and len(descriptor['sha256'])==64
             and all(v in '0123456789abcdef' for v in descriptor['sha256']),
             'PXD_BASIS_EXACT_DESCRIPTOR_FILENAME_BEFORE_READ')
        raw=(Path(root)/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'PXD_BASIS_EVERY_ACTUAL_DESCRIPTOR_BYTES')
        if json.loads(raw)['schema']==SCHEMA:present.append(descriptor)
    need(len(present)<=1,'PXD_BASIS_ONLY_ONE_PREOPEN_STOCK_SCOPE')
    four=previous.previous.previous.original_preflight
    models=four.MODELS|{previous.previous.previous.SCHEMA,previous.previous.SCHEMA,previous.SCHEMA}
    if present:models|={SCHEMA}
    return cloned(four.documents,MODELS=models)(root,cp)


def validate_closing(root,cp):
    return cloned(previous.validate,documents=documents)(root,cp)


def validate(root,cp):
    need(cp['run']['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs'])),
         'PXD_BASIS_FULL_ACTUAL_INPUT_COMMITMENT')
    found=[]
    for descriptor,value in documents(root,cp):
        if value['schema']!=SCHEMA:continue
        obj=parse(Path(root)/'book/repairs'/descriptor['filename'],
            resume_session=descriptor['resume_session'],
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'],
            expected_repair=expected_repair(root,descriptor['predecessor_checkpoint_sha256']),
            expected_evidence=evidence(root))
        need(obj.sha256==descriptor['sha256'],'PXD_BASIS_EXACT_EIGHTH_TYPED_DESCRIPTOR')
        found.append(obj)
    return found


def validate_all(root,cp):
    actual=documents(root,cp)
    four=previous.previous.previous.original_preflight
    first,body=cloned(four.validate_models,documents=documents)(root,cp)
    chinook,=previous.previous.previous.validate(root,cp)
    outcome,_=previous.previous.retained(root,cp)
    closing,=validate_closing(root,cp)
    need(outcome is not None,'PXD_BASIS_RETAINED_ORIGINAL_PROOF_BOUNDARY_REQUIRED')
    expected={**first,previous.previous.previous.SCHEMA:chinook.sha256,
              previous.previous.SCHEMA:outcome.sha256,previous.SCHEMA:closing.sha256}
    own=validate(root,cp)
    if own:expected[SCHEMA]=own[0].sha256
    typed={value['schema']:descriptor['sha256'] for descriptor,value in actual
           if value['schema']!='terminal-repair/1'}
    need(typed==expected,'PXD_BASIS_ALL_SEVEN_OR_EIGHT_ACTUAL_PARSERS_MATCH_FULL_INPUT_SET')
    return expected,body


def semantic_visitor():
    sources();fn=previous.semantic_visitor()
    need('ADDITIONAL_SCHEMAS' in fn.__globals__,'PXD_BASIS_EXPLICIT_VALIDATED_SCHEMA_CLASSIFICATION')
    return cloned(fn,ADDITIONAL_SCHEMAS=set(fn.__globals__['ADDITIONAL_SCHEMAS'])|{SCHEMA})


def common_scope(root):
    event=contract()['event']
    return dict(schema=SCHEMA,scope=SCOPE,require_unowned_and_unordered=True,
        require_no_entry_intents=True,morning_settlement_claimed=False,source_evidence=evidence(root),
        event={k:event[k] for k in ('security_id','native_session','session','preopen_completion_claimed',
            'exact_effective_clock_claimed','ordinary_common_only','primary_source','primary_sections')})


def append_semantics(before,obj,refs,scope):
    value=deepcopy(before)
    value['schema']='research.system-campaign-common-unowned-preopen-stock-basis/1'
    value['factual_semantics']=merge_semantics(before['factual_semantics'],obj.canonical_repair,refs)
    value['factual_semantics_sha256']=digest(value['factual_semantics'])
    value['model_semantics'].append(deepcopy(scope))
    return value


def basis(root,cp,*,amendment):
    own=validate(root,cp)
    if not own:return previous.basis(root,cp,amendment=amendment)
    validate_all(root,cp)
    old_body=cloned(previous.basis,validate=validate_closing,validate_all=validate_all,
                    semantic_visitor=semantic_visitor)
    _,old=old_body(root,cp,amendment=amendment)
    obj,=own
    value=append_semantics(old,obj,{v['reference']:v['sha256'] for v in evidence(root)},common_scope(root))
    return digest(value),value


def require_exact_delta(before,after,obj,root):
    expected=append_semantics(before,obj,{v['reference']:v['sha256'] for v in evidence(root)},common_scope(root))
    need(after==expected,'PXD_BASIS_ONLY_NEW_FACT_AND_SCOPE_ALL_SEVEN_PRIOR_MODELS_UNCHANGED')
    return True


class EightModelPreflight:
    def __init__(self,cp,root):
        self.root=Path(root).resolve();self.binding=digest(cp)
        self.models,self.body=validate_all(self.root,cp)
        self.close,=validate_closing(self.root,cp)
        self.pxd,=validate(self.root,cp)
        six=previous.six
        need(set(self.models)==six.prior.MODELS|{six.CHINOOK,six.OUTCOME,previous.SCHEMA,SCHEMA},
             'PXD_PREFLIGHT_ALL_EIGHT_ACTUAL_INPUTS_REQUIRED')
        self.bodies=(self.body,self.close.canonical_repair,self.pxd.canonical_repair)
        self.model_ids={'941065113449292610','732226698577723721','1050970006012443443',
                        '47247117758471252','533554648046407798','276044719892003870'}
        self.model_ids.update(v['security_id'] for body in self.bodies for k in ('suppress','add') for v in body[k])
        fn=six.prior.compile_visitor(Path(six.prior.ordinary.__file__).read_bytes())
        self.visit=cloned(fn,VALIDATED_ADDITIONAL_SCHEMAS=(six.prior.MODELS-{six.prior.ALDER})
            |{six.CHINOOK,six.OUTCOME,previous.SCHEMA,SCHEMA})

    def analyze(self,cp,root,catalog):
        need(digest(cp)==self.binding and Path(root).resolve()==self.root,
             'PXD_PREFLIGHT_EXACT_FULL_VALIDATED_CHECKPOINT_AND_ROOT')
        documents(self.root,cp)
        value=self.visit(cp,root,catalog)
        extra=[v for body in self.bodies
               for v in previous.six.prior.extra_collisions(catalog,body,self.model_ids)]
        need(not extra,'PXD_PREFLIGHT_ALL_TYPED_AND_THREE_GUARDED_KEY_SETS_DISJOINT')
        value.update(validated_nonordinary_input_sha256=self.models,
            guarded_canonical_keys_checked=sum(len(body[k]) for body in self.bodies for k in ('suppress','add')),
            full_actual_input_commitment_verified=True,descriptor_or_financial_checkpoint_projection=False)
        return value
