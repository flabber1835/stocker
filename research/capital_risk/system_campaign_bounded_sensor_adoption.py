"""One explicit filename binding for the entire original neutral adoption gate."""
import ast
from copy import deepcopy
from pathlib import Path
import system_campaign_financial_uncertainty as original
from system_campaign_bounded_sensor_input import need,sha
from system_campaign_bounded_sensor_lifecycle_data import DIRECTORY,DOCUMENT,validate_document

ORIGINAL_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'

def adoption_tree(raw):
    need(sha(raw)==ORIGINAL_SHA,'BOUNDED_ADOPTION_ENTIRE_ORIGINAL_HELPER_SOURCE')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
    site=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    need(len(site)==1 and isinstance(site[0].value,ast.Dict),'BOUNDED_ADOPTION_ONE_ORIGINAL_FILENAME_MAP')
    mapping=site[0].value
    need([ast.unparse(k) for k in mapping.keys]==['ORDINARY_ADOPTION','DATE_ADOPTION','MODEL_ADOPTION']
         and [ast.unparse(v) for v in mapping.values]==["'future-financial-overlay.json'",'DATE_OVERLAY',"'branch-uncertainty-input.json'"],
         'BOUNDED_ADOPTION_EXACT_OLD_THREE_FILENAME_ENTRIES')
    mapping.keys.append(ast.Constant(DIRECTORY));mapping.values.append(ast.Constant(DOCUMENT))
    return ast.fix_missing_locations(fn)

def adopter():
    fn=adoption_tree(Path(original.__file__).read_bytes());namespace=dict(vars(original))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<entire-original-pause-one-bounded-input-filename>','exec'),namespace)
    return namespace['paused_own_adoption']

def adopt(parent,out,args,rows,catalog,codec):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest
    from system_campaign_financial_partial import root_spec
    need((parent['sha256'],parent['source_cursor'],parent['completed'])==
         (catalog['parent_outer_sha256'],catalog['parent_cursor'],catalog['parent_completed'])
         and parent['repairs']==catalog['parent_descriptors'], 'BOUNDED_ADOPTION_EXACT_FULL_ACTUAL_PARENT')
    need(getattr(backtest.load_repair,'__self__',None) is codec
         and codec.event==catalog['event'] and codec.evidence==
             [item.model_dump() for item in validate_document(Path(out)/DOCUMENT,catalog,root_lookup=root_spec).source_evidence],
         'BOUNDED_ADOPTION_SAME_ACTIVE_TYPED_INPUT_CODEC')
    typed=validate_document(Path(out)/DOCUMENT,catalog,root_lookup=root_spec)
    current=adopter()(parent,Path(out),args,rows,Path(out)/DOCUMENT,catalog['event']['native_session'],DIRECTORY)
    from system_campaign_bounded_sensor_models import validate_full
    from system_campaign_bounded_sensor_lifecycle_data import evidence,descriptor
    validate_full(out,current,catalog,evidence(catalog));descriptor(current,catalog,typed)
    need(current['repairs'][:-1]==parent['repairs'] and current['run']['state']==parent['run']['state']
         and current['completed']==parent['completed'] and current['source_cursor']==parent['source_cursor'],
         'BOUNDED_ADOPTION_ONLY_NEW_INPUT_IDENTITY_NO_FINANCIAL_TRANSITION')
    return current
