"""Whole original future input API with explicit finite fourteen-term selectors."""
import ast,csv,gzip,io,json,zipfile
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p03_thor_api as prior
import system_campaign_p03_cash14_data as data
HERE=Path(__file__).parent
OVERLAY='p03-cash14-ordinary18-overlay.json'
DIRECTORY='p03-cash14-ordinary18-adoption'
QUALIFICATION='p03-cash14-ordinary18-input-qualification.json'
FUNCTIONS=prior.FUNCTIONS
def provider(path):
    from system_campaign_2021_completions_facts import require_alias_archive,require_alias_rows
    raw=Path(path).read_bytes();require_alias_archive(raw);term,=[t for t in data.terms() if t['ticker']=='BEAT1'];rows=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for n in z.namelist():
            with z.open(n) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream,encoding='utf8',newline='')):
                    if row['date']==term['native_session'] and term['ticker'] in (row['ticker'],row['contraticker']):rows.append(row)
    require_alias_rows(rows,term)
    return dict(passed=True,provider_sha256=data.sha(raw),provider_bytes=len(raw),BEAT1_original_rows=5,metadata_upgraded=False)
def qualifier_save(path,value):
    path=Path(path)
    if path.name=='future-input-qualification.json':
        data.need(value['passed'] is True and value['packet_checks']==28 and value['financial_sessions_advanced']==0,'P03_14_WHOLE_ORIGINAL28_PACKET_CHECKS')
        path=path.with_name(QUALIFICATION)
    return original.save(path,value)
def api(parent,spec,*,provider_root=Path('/out')):
    data.parent_contract(parent,spec);codec=data.codec(parent,spec);terms=data.terms()
    data.need(data.sha(Path(original.__file__).read_bytes())==prior.FUTURE_SHA,'P03_14_WHOLE_ORIGINAL_FUTURE_SOURCE')
    def selected(arm,*,cursor=None):
        data.need((arm,cursor)==('P03','2020-01-31'),'P03_14_ONE_EXACT_ACTUAL_PARENT_CLOCK')
        return codec,data.CATALOG,deepcopy(terms)
    from system_campaign_bounded_sensor_input import SCHEMA
    namespace=dict(vars(original),__file__=__file__,HERE=HERE,selected=selected,OVERLAY=OVERLAY,
        completion_session=data.completion_session,validate_input=prior.full_branch_input,
        validate_dova_input=prior.validate_dova_input,DOVA_SCHEMA=SCHEMA)
    # The selected codec already composes exactly the fourteen qualified terms.
    # The two original unselected catalog routes have no authority in this API.
    namespace['original_ordinary_selection']=lambda arm,cursor:None
    namespace['supplemental_selection']=lambda arm,cursor:([],[])
    fn=prior.remaining_tree(Path(original.__file__).read_bytes())
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-remaining-full17-and18-DOVA-visitor>','exec'),namespace)
    for name in FUNCTIONS:
        fn=getattr(original,name);data.need(fn.__closure__ is None,'P03_14_ORIGINAL_API_NO_HIDDEN_CLOSURE')
        bound=FunctionType(fn.__code__,dict(namespace,save=qualifier_save) if name=='qualify' else namespace,fn.__name__,fn.__defaults__)
        bound.__kwdefaults__=deepcopy(fn.__kwdefaults__);data.need(bound.__code__ is fn.__code__,'P03_14_WHOLE_ORIGINAL_API_FUNCTION_CODE:'+name)
        namespace[name]=bound
    whole=namespace['hydrate']
    def hydrate(current,arm,*,source_root=None):
        original.hosted();data.parent_contract(current,spec)
        paths=([Path(source_root)/'provider-source/SHARADAR_ACTIONS.zip'] if source_root is not None else [])+[Path(provider_root)/'provider-source/SHARADAR_ACTIONS.zip']
        found=[p for p in paths if p.is_file()];data.need(found,'P03_14_ACTUAL_STAGED_PROVIDER_OBJECT_REQUIRED')
        proofs=[provider(p) for p in found];data.need(all(v==proofs[0] for v in proofs),'P03_14_NO_CONFLICTING_RETAINED_PROVIDER_OBJECT')
        # Independently prove the real final native-day quote. This is a normal
        # frozen provider read, not a relabeled old source-capture generation.
        from research.pooled_input_support import inputs
        target=data.facts()['source_files']['P03-own524-14cash-role-and-DERM-boundary-DATA.json']
        closed=json.loads((HERE/'P03-own524-14cash-role-and-DERM-boundary-DATA.json').read_bytes())
        seen={}
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as z:
            for row in inputs._archive_rows(z,'observations-2020.csv.gz'):
                if row['security_id']==data.SID and '2020-02-18'<=row['session']<='2020-02-20':
                    data.need(row['session'] not in seen,'P03_14_UNIQUE_COMPLETE_NATIVE_BOUNDARY_ROW');seen[row['session']]=row
        data.need(seen==closed['complete_native_boundary_rows'] and seen['2020-02-19']['tradeable']=='1'
            and seen['2020-02-19']['raw_close']=='18.75' and '2020-02-20' not in seen,'P03_14_REAL_FEB19_QUOTE_AND_FEB20_ABSENCE_NO_EARLY_CASH')
        material,delivered,actions=whole(current,arm,source_root=source_root)
        _,components=data.supplemental()
        data.need('ordinary_components' not in material and not delivered,'P03_14_ONLY_DECLARED_FOUR_ORIGINAL_CASH_COMPONENTS')
        material['ordinary_components']=deepcopy(components)
        return material,delivered,actions
    namespace['hydrate']=hydrate
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},selected=selected,OVERLAY=OVERLAY,
        whole_original_hydrate=whole,original_namespace=namespace)
def source_names():return (Path(__file__).name,*data.source_names())
