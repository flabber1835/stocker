"""Exact ordinary semantics and two separately validated sensor commitments."""
import ast,json,hashlib
from copy import deepcopy
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import digest
from system_campaign_zogenix_input import SCHEMA,parse
from system_campaign_zogenix_facts import CONTRACT,evidence
import system_campaign_uncertainty_basis as old


def validate(root,cp):
    matches=[];contract=json.loads((Path(__file__).parent/CONTRACT).read_bytes())
    for d in cp['repairs']:
        path=root/'book/repairs'/d['filename'];raw=path.read_bytes()
        need(hashlib.sha256(raw).hexdigest()==d['sha256'],'ZOGENIX_ALL_INPUT_BYTES')
        if json.loads(raw)['schema']!=SCHEMA:continue
        obj=parse(path,resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'],
                  expected_evidence=evidence(root),native_sha256=contract['native_term_sha256'])
        need(d['filename']==obj.sha256+'.json' and obj.sha256==d['sha256'],'ZOGENIX_EXACT_DESCRIPTOR')
        matches.append(obj)
    need(len(matches)<=1,'ZOGENIX_ONLY_ONE_ADDITIONAL_MODEL')
    return matches


def projected_original_basis():
    """Only the semantic visitor recognizes the validated additional schema."""
    raw=Path(old.__file__).read_bytes();contract=json.loads((Path(__file__).parent/CONTRACT).read_bytes())
    need(hashlib.sha256(raw).hexdigest()==contract['inherited_sources']['system_campaign_uncertainty_basis.py'],
         'ZOGENIX_EXACT_OLD_BASIS_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='basis']
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='descriptor']
    # Insert after authenticated JSON parsing, before classification. No input
    # or checkpoint is fabricated; the full real cp is validated and retained.
    site,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='document']
    loop.body.insert(site+1,ast.parse("if document['schema']==ADDITIONAL_SCHEMA: continue").body[0])
    scope=dict(vars(old),ADDITIONAL_SCHEMA=SCHEMA)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<validated-second-sensor-semantic-visitor>','exec'),scope)
    return scope['basis']


def basis(root,cp,*,amendment):
    from research.pooled_vacancy_funding import backtest
    need(cp['run']['input_sha256']==backtest.input_hash(cp['base'],cp['repairs']),'ZOGENIX_ACTUAL_FULL_INPUT_COMMITMENT')
    models=validate(root,cp)
    if not models:return old.basis(root,cp,amendment=amendment)
    _,prior=projected_original_basis()(root,cp,amendment=amendment)
    new=models[0].model_dump(by_alias=True);new.pop('predecessor_checkpoint_sha256')
    value=dict(schema='research.system-campaign-common-joint-sensor-basis/1',
        factual_semantics_sha256=prior['factual_semantics_sha256'],factual_semantics=prior['factual_semantics'],
        model_semantics=[deepcopy(prior['model_semantics']),new],
        price_or_probability_estimate_selected=False,independent_uncertainty_assumption=False)
    return digest(value),value
