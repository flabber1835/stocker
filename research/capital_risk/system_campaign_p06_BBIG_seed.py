"""Whole retained seed with explicit full visitor and original ABMD DAY reader."""
import ast,json
from copy import deepcopy
from pathlib import Path
import system_campaign_financial_uncertainty as legacy
import system_campaign_p06_abmd_point_continuation as point
import system_campaign_p06_abmd_initial_certificate as initial
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_models as models

U_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'
POINT_SHA='02135148c5f5f60b503332b4fbbe60ffaa4c6c06c9a9340db7c7e35f59b32f9a'
FULL=dict(bytes=2510480,sha256='fbb3fb5eaebb71ac6c4489d537968fd015832c8444402ec5bafb0f3b9b6ee56e')
PREFIX=dict(bytes=2218200,sha256='0bdfa51bfa0f35b62387ae2cd007ebb6b650a33d5d24fb5cdee2d63afb394e53')
LAST='77ead10eb00907311069f553e4308de612f8800e95ba3b60c8d1e353a7ce533c'
def phase(spec):
    data.need(spec['arm']=='P06' and spec['root_admission_sha256']==data.ROOT,'P06_BBIG_ONLY_ACTUAL130_PHASE')
    return dict(rows=130,new_rows=124,retained_rows=6)
def seed_tree(raw):
    data.need(data.sha(raw)==U_SHA,'P06_BBIG_WHOLE_ORIGINAL_RETAINED_SEED_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='retained_seed']
    imp,=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches']
    data.need([(v.name,v.asname) for v in imp.names]==[('validate_input',None),('seed',None),('discrete',None),('digest',None)],
        'P06_BBIG_EXACT_ORIGINAL_SEED_IMPORTS_BEFORE_TWO_LIFTS')
    imp.names=imp.names[2:]
    return ast.fix_missing_locations(fn)
def bind_seed(*,contract,visitor=models.full,reader=None):
    reader=initial.seed_reader(inherited_root=Path(point.__file__).parent) if reader is None else reader
    data.need(all(callable(v) for v in (contract,visitor,reader)),'P06_BBIG_EXPLICIT_WHOLE_SEED_BINDINGS')
    namespace=dict(vars(legacy),retained_contract=contract,retained_phase=phase,validate_input=visitor,seed=reader)
    exec(compile(ast.Module(body=[seed_tree(Path(legacy.__file__).read_bytes())],type_ignores=[]),'<whole-original-retained-seed-full-history-and-ABMD-DAY>','exec'),namespace)
    return namespace['retained_seed']
def metadata_tree(raw):
    data.need(data.sha(raw)==POINT_SHA,'P06_BBIG_WHOLE_ORIGINAL_POINT_METADATA_SOURCE')
    fn=point.function(raw,'qualify_seed_metadata')
    changes={13478656632:13482378564,1259:1383,'2022-12-30':'2023-06-30'}
    counts={}
    for node in ast.walk(fn):
        if isinstance(node,ast.Constant) and type(node.value) in (str,int) and node.value in changes:
            old=node.value;node.value=changes[old];counts[old]=counts.get(old,0)+1
    data.need(counts=={13478656632:1,1259:1,'2022-12-30':2},'P06_BBIG_FINITE_POINT_METADATA_ACTUAL1383_SITES')
    proof_guard,=[n.value for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='P06_POINT_LITERAL_SIX_ADMITTED_PROOFS_NO_UNADMITTED_TAIL' for v in n.value.args)]
    replacements={"proof['rows'] == 6":124,"proof.get('retained_rows', 0) == 0":6,
        'len(rows) == len(committed) == 6':130}
    sites=[n for n in ast.walk(proof_guard.args[0]) if isinstance(n,ast.Compare) and ast.unparse(n) in replacements]
    data.need(len(sites)==3,'P06_BBIG_EXACT_OLD_6_NEW_RETAINED_AND_LENGTH_SITES')
    for node in sites:node.comparators[-1]=ast.Constant(replacements[ast.unparse(node)])
    fn.args.kw_defaults[-1]=ast.Name(id='PREFIX',ctx=ast.Load())
    return ast.fix_missing_locations(fn)
def qualify_metadata(current,spec,rows,committed,resolutions,allowed,archive,hashes,expected):
    data.parent_contract(current,spec)
    namespace=dict(vars(point),SAVED_OUTER=data.OUTER,SAVED_GZIP=spec['selected_file'],LAST_CHAIN=LAST,PREFIX=PREFIX)
    exec(compile(ast.Module(body=[metadata_tree(Path(point.__file__).read_bytes())],type_ignores=[]),'<whole-original-point-metadata-exact130-admission>','exec'),namespace)
    result=namespace['qualify_seed_metadata'](current,spec,rows,committed,resolutions,allowed,archive,hashes,expected)
    # The old result labels are provenance, never returned as a new six-row assertion.
    data.need(result['passed'] is True,'P06_BBIG_WHOLE_METADATA_PASSED')
    return dict(passed=True,committed_rows=130,exact_literal130_prefix_preserved=True,
        unadmitted_tail_rows_used=0,second_event_authorized=False,financial_authority=False)
def prior_event(root,current,rows,parent):
    from system_campaign_bounded_sensor_event_review import permissions
    import system_campaign_p06_abmd_lifecycle_data as lifecycle
    data.need(current['base']==parent['base'] and current['repairs'][:10]==parent['repairs'],
        'P06_BBIG_HISTORICAL_EVENT_EPOCH10_RETAINED_IN_REAL_CURRENT_HISTORY')
    allowed,resolutions=permissions(Path(root),rows,lifecycle.catalog(),through=parent['source_cursor'],input_descriptors=parent['repairs'])
    data.need(allowed=={} and len(resolutions)==1 and rows[0]['bounded_event_basis']['selected'] is False,
        'P06_BBIG_ONE_ACTUAL_PRIOR_ABMD_ARCHIVE_NO_NEW_PERMISSION')
    return allowed,resolutions
def whole_prefix(root,parent,rows):
    raw=(Path(root)/'uncertainty-certificate.jsonl').read_bytes();lines=raw.splitlines(keepends=True)
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==FULL and len(lines)==147 and len(rows)==130
        and point.proof_bytes(rows)==b''.join(lines[:130]) and all(json.loads(v)['session']>parent['source_cursor'] for v in lines[130:])
        and dict(bytes=len(point.proof_bytes(rows)),sha256=data.sha(point.proof_bytes(rows)))==PREFIX,
        'P06_BBIG_LITERAL130_ADMITTED_PREFIX_EXCLUDES_ALL17_RAW_TAILS')
    return True
def contract(parent,spec,root):
    data.parent_contract(parent,spec)
    hashes=json.loads((Path(point.__file__).parent/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
    data.need(len(hashes)==6 and all(parent['base']['sources'].get(n)==h and data.sha((Path('/variant')/n).read_bytes())==h for n,h in hashes.items()),
        'P06_BBIG_ALL_SIX_UNCHANGED_ACTUAL_PHYSICAL_CONTROLLER_SOURCES')
    point.arithmetic_sources(Path('/variant/sentinel/controller/median5.py').read_bytes(),
        (Path(point.__file__).parent/'system_campaign_point_growth.py').read_bytes(),
        (Path(point.__file__).parent/'system_campaign_financial_additional_sensor.py').read_bytes())
    from system_campaign_point_growth import point_growth
    point_growth(())
    return hashes
def original_seed(root,parent,spec):
    from full_system_core import hosted
    hosted();root=Path(root)
    checked=bind_seed(contract=lambda current,target:contract(current,target,root))(root,parent,spec)
    hashes,rows,qualified=checked;whole_prefix(root,parent,rows)
    import system_campaign_p06_abmd_lifecycle_data as lifecycle
    import system_campaign_p06_abmd_models as oldmodels
    lifecycle.checked_resources(root/oldmodels.DIRECTORY/'prior-resources',lifecycle.plan())
    allowed,resolutions=prior_event(root,parent,rows,parent);archive=(root/resolutions[0]['actual']).read_bytes()
    qualify_metadata(parent,spec,rows,rows,resolutions,allowed,archive,hashes,hashes)
    return hashes,rows,qualified,resolutions[0]
def certificate_class(event,source,codec,native,*,inherited_root,retained_root,current_checkpoint,admitted_spec):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_p06_abmd_lifecycle_data as lifecycle
    root=Path(retained_root);neutral=current_checkpoint;spec=admitted_spec
    parent=journal.read_checkpoint(root/models.PARENT);data.parent_contract(parent,spec)
    from system_campaign_p06_BBIG_runtime import boundary_relation
    from system_campaign_financial_resume import seed_rows
    boundary_relation(parent,neutral,spec,lambda n:(root/n).read_bytes(),seed_rows(root,parent,spec))
    models.full(root,neutral)
    value=lifecycle.catalog();data.need(event==value['event'] and source==value['market_source'],'P06_BBIG_UNCHANGED_ABMD_EVENT_AND_SOURCE')
    hashes,rows,qualified,resolution=original_seed(root,parent,spec);archive=(root/resolution['actual']).read_bytes()
    def qualified_retained_seed(actual,source_hashes,actual_event,actual_source,actual_codec):
        data.need(actual_event==event and actual_source==source and actual_codec is codec
            and (root/resolution['actual']).read_bytes()==archive,'P06_BBIG_FRESH_ACTUAL_ARCHIVE_CODEC_AND_SOURCE')
        qualify_metadata(parent,spec,actual,rows,[resolution],{},archive,source_hashes,hashes)
        data.need(data.sha(Path('/variant/sentinel/controller/median5.py').read_bytes())==point.WITNESS_SHA,
            'P06_BBIG_FRESH_UNALTERED_WITNESS_SOURCE')
        return True
    scope=dict(vars(initial),mixed_growth=point.mixed_growth,qualified_retained_seed=qualified_retained_seed)
    exec(compile(ast.Module(body=[point.factory_tree(Path(initial.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-ABMD-factory-qualified130-and-same-point-growth>','exec'),scope)
    return scope['certificate_class'](event,source,codec,native,inherited_root=inherited_root)
def suffix(parent,current,retained,rows,financial,*,median5,champion_config):
    from full_system_core import hosted
    hosted()
    from system_campaign_p06_abmd_retained_suffix import bind_review
    data.need(len(retained)==130 and not any(row['session']=='2022-12-22' for row in rows),
        'P06_BBIG_ALL130_RETAINED_NO_REPLAYED_ABMD_EVENT')
    return bind_review()(parent,current,retained,rows,financial,median5=median5,champion_config=champion_config)
def source_names():return (Path(__file__).name,*models.source_names())
