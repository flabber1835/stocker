"""Private full legacy runtime namespace with one source-bound third event."""
import ast,json,shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_ordinary_augmentation_data as legacy_data
import system_campaign_ordinary_augmentation_runtime as legacy_runtime
import system_campaign_p07_abmd_models as models
import system_campaign_p07_abmd_origin as origin
ARCHIVE_SHA='a0d82bf28260ffe47b814ad0ff90cbec4185c695e0b2d69a603ab490582543b7'

def suffix(cp,plan):
    if len(cp['repairs'])==22:
        legacy_data.parent_scope(cp,plan);return []
    need(cp['repairs'][:22]==plan['parent_descriptors'] and cp['repairs'][:23]==models.plan()['parent_descriptors']
         and len(cp['repairs']) in (23,24),'P07_ABMD_ORIGINAL23_PREFIX_AND_ONE_NEW_MODEL')
    return cp['repairs'][22:23]

def neutral_input_hashes(successor,current,value,input_hash):
    return (successor['repairs']==current['repairs'][:23]
        and successor['run']['input_sha256']==value['adopted_input_sha256']==input_hash(successor['base'],successor['repairs'])
        and current['run']['input_sha256']==input_hash(current['base'],current['repairs']))

def neutral_tree(raw):
    fn=legacy_data.original.function(raw,'verify_neutral')
    fn=models.replace(fn,"successor['repairs'] == current['repairs']","successor['repairs'] == current['repairs'][:23]",
        'P07_ABMD_ONE_ORIGINAL_NEUTRAL_RECEIPT_BOUNDARY')
    fn=models.replace(fn,"successor['run']['input_sha256'] == current['run']['input_sha256']",
        'neutral_input_hashes(successor,current,value,canonical_hash())','P07_ABMD_ONE_ORIGINAL_NEUTRAL_RECEIPT_HASH')
    return ast.fix_missing_locations(fn)

def runtime_tree(raw):
    tree=legacy_data.runtime_tree(raw)
    review=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review')
    # ast represents data.need as an Attribute; bind the exact labeled site.
    guards=[n for n in ast.walk(review) if isinstance(n,ast.Call) and ast.unparse(n.func)=='data.need'
            and any(isinstance(v,ast.Constant) and v.value=='ADDITIONAL_COMMITTED_EVENT_PREIMAGE_PROOF_REQUIRED' for v in n.args)]
    need(len(guards)==1 and ast.unparse(guards[0].args[0])=='len(resolutions) == 1',
         'P07_ABMD_ONE_ORIGINAL_COMMITTED_EVENT_PERMISSION_COUNT')
    guards[0].args[0]=ast.parse('resolution_counts_valid(resolutions,current)',mode='eval').body
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_retained')
    imports=[n for n in run.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_uncertainty_archive']
    need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==[('preserve','preserve_event')],
         'P07_ABMD_ONE_ARCHIVE_PRESERVER_IMPORT_BINDING')
    run.body.remove(imports[0])
    return ast.fix_missing_locations(tree)

def active_tree(raw):
    fn=legacy_data.original.function(raw,'active_branch')
    site=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='installed']
    need(len(site)==1 and ast.unparse(site[0].value)=='backtest.load_repair',
         'P07_ABMD_ONE_OLD_LOADER_CHAIN_INSPECTION_SITE')
    site[0].value=ast.parse('qualified_lower_loader(backtest.load_repair)',mode='eval').body
    return ast.fix_missing_locations(fn)

def review_ordinary_tree(raw):
    fn=legacy_data.original.function(raw,'review_ordinary')
    fn=models.replace(fn,"parent['repairs'] == current['repairs']",
        'review_bounded_origin(parent,current,evidence,out,spec)','P07_ABMD_ONE_EXACT_NEW_NEUTRAL_REVIEW_SITE')
    return ast.fix_missing_locations(fn)

def future_tree(raw):
    fn=legacy_data.original.function(raw,'future_api')
    matches=[n for n in ast.walk(fn) if isinstance(n,ast.Compare)
             and ast.unparse(n)=="entry in [phase['original_branch_descriptor'], *modeled]"]
    need(len(matches)==1,'P07_ABMD_ONE_ORDINARY_TYPED_COMPOSITION_SITE')
    old=deepcopy(matches[0]);replacement=ast.BoolOp(op=ast.Or(),values=[old,
        ast.parse("len(cp['repairs'])==24 and entry==cp['repairs'][23]",mode='eval').body])
    class Replace(ast.NodeTransformer):
        def visit_Compare(self,node):return replacement if node is matches[0] else self.generic_visit(node)
    return ast.fix_missing_locations(Replace().visit(fn))

def safe_copy(source,target):
    source,target=Path(source),Path(target)
    if source.resolve()==target.resolve():
        need(source.is_file() and source.read_bytes()==target.read_bytes(),'P07_ABMD_IDEMPOTENT_SAME_AUTHENTIC_RESOURCE')
        return str(target)
    return shutil.copyfile(source,target)

def save_archive_receipt(path,value):
    """Exact existing metadata only; original exclusive saver creates new files."""
    from full_system_benchmark import save
    path=Path(path)
    need(path.name=='uncertainty-event-archive-preservation.json',
         'P07_ABMD_ONLY_ORIGINAL_ARCHIVE_RECEIPT_METADATA')
    if not path.exists():return save(path,value)
    need(path.is_file() and path.read_bytes()==origin.encoded(value),
         'P07_ABMD_EXISTING_ARCHIVE_RECEIPT_EXACT_BYTES_NO_OVERWRITE')

def archive_tree(raw):
    need(sha(raw)==ARCHIVE_SHA,'P07_ABMD_WHOLE_ORIGINAL_ARCHIVE_SOURCE')
    fn=legacy_data.original.function(raw,'preserve')
    guards=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='need'
            and any(isinstance(v,ast.Constant) and v.value=='UNCERTAINTY_ARCHIVE_DISJOINT_NEW_EVIDENCE' for v in n.args)]
    need(len(guards)==1 and ast.unparse(guards[0].args[0])=='not target.exists()',
         'P07_ABMD_ONE_ORIGINAL_ARCHIVE_DISJOINT_GUARD')
    guards[0].args[0]=ast.parse('not target.exists() or same_existing_archive(actual,target,proof)',mode='eval').body
    return ast.fix_missing_locations(fn)

def archive_resolver_tree(raw):
    need(sha(raw)==ARCHIVE_SHA,'P07_ABMD_WHOLE_ORIGINAL_ARCHIVE_RESOLVER_SOURCE')
    fn=legacy_data.original.function(raw,'resolve')
    class Source(ast.NodeTransformer):
        hits=0
        def visit_Constant(self,node):
            if node.value=='uncertainty-certificate.jsonl':
                self.hits+=1;return ast.copy_location(ast.Constant(origin.DIRECTORY+'/prior-committed-certificate.jsonl'),node)
            return node
    adapter=Source();fn=adapter.visit(fn);need(adapter.hits==1,'P07_ABMD_ONE_AUTHENTICATED_PRIOR_PROOF_READ_PATH')
    return ast.fix_missing_locations(fn)

def added_permissions(where,rows,catalog,current,reader):
    day=catalog['event']['effective_session']
    # New suffixes starting after the event contain no new event. The complete
    # original593-relative proof pass below still requires its one resolution.
    if not rows or rows[0]['session']>day:return {},[]
    return reader(where,rows,catalog,through=rows[-1]['session'],input_descriptors=current['repairs'])

def build(root,cp,spec,catalog,*,phase,root_metadata,review_bounded_origin,seed_bridge=None):
    from full_system_core import hosted
    hosted()
    models.plan()
    from research.pooled_vacancy_funding import backtest
    from system_campaign_bounded_sensor_input import InputCodec
    from system_campaign_abmd_bounded_catalog import evidence
    import system_campaign_financial_additional_sensor_runtime as original
    import system_campaign_uncertainty_archive as archive
    from system_campaign_bounded_sensor_event_review import permissions
    from system_campaign_p07_abmd_certificate import certificate_class,DAY
    old_plan=legacy_data.catalog();validator=models.legacy_validator(catalog,evidence(catalog),root_metadata)
    additional_proxy=SimpleNamespace(**dict(vars(legacy_data.original),phase=phase,
        selected_declaration=lambda where,actual,selected:phase(selected)))
    proxy=SimpleNamespace(**dict(vars(legacy_data),suffix=suffix,validator=lambda ignored:validator,original=additional_proxy))
    def receipt(where,actual,ignored,*,input_hash):
        if len(actual['repairs'])==22:return legacy_data.validated_receipt(where,actual,old_plan,input_hash=input_hash)
        return models.read_legacy_receipt(where,actual,input_hash=input_hash)
    proxy.validated_receipt=receipt
    proxy.runtime_tree=runtime_tree
    ordinary_scope=dict(vars(legacy_runtime),data=proxy,neutral_input_hashes=neutral_input_hashes,
        review_bounded_origin=review_bounded_origin)
    raw=Path(legacy_runtime.__file__).read_bytes()
    need(sha(raw)==models.plan()['source_files'][Path(legacy_runtime.__file__).name],
         'P07_ABMD_WHOLE_LEGACY_ORDINARY_RUNTIME_SOURCE')
    nodes=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)]
    for i,node in enumerate(nodes):
        if node.name=='verify_neutral':nodes[i]=neutral_tree(raw)
        elif node.name=='review_ordinary':nodes[i]=review_ordinary_tree(raw)
        elif node.name=='future_api':nodes[i]=future_tree(raw)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<whole-legacy-ordinary-runtime-full24-input-metadata>','exec'),ordinary_scope)
    old_api=ordinary_scope['api'](root,cp,spec);namespace=old_api.run.__globals__
    # Every existing additional/model contract uses the actual separately qualified phase.
    namespace['data'].phase=lambda selected:phase(selected)
    namespace['data'].selected_declaration=lambda where,actual,selected:phase(selected)
    source_shutil=SimpleNamespace(**dict(vars(shutil),copyfile=safe_copy))
    namespace['shutil']=source_shutil
    def same_existing_archive(actual,target,proof):
        return (Path(actual).resolve()==Path(target).resolve() and Path(target).is_file()
            and sha(Path(target).read_bytes())==proof['file_sha256'])
    archive_scope=dict(vars(archive),shutil=source_shutil,same_existing_archive=same_existing_archive,save=save_archive_receipt)
    archive_raw=Path(archive.__file__).read_bytes()
    exec(compile(ast.Module(body=[archive_resolver_tree(archive_raw),archive_tree(archive_raw)],type_ignores=[]),
        '<whole-original-archive-preserver-exact-idempotent-self-source>','exec'),archive_scope)
    namespace['preserve_event']=archive_scope['preserve']
    def qualified_lower_loader(installed):
        codec=getattr(installed,'__self__',None)
        need(isinstance(codec,InputCodec) and installed==codec.load and codec.event==catalog['event']
             and codec.objects,'P07_ABMD_ACTUAL_INSTALLED_OUTER_TYPED_CODEC')
        return codec.original_load
    namespace['qualified_lower_loader']=qualified_lower_loader
    exec(compile(ast.Module(body=[active_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-chain-inspector-under-one-qualified-outer-codec>','exec'),namespace)
    def joint(mixed):
        codec=getattr(backtest.load_repair,'__self__',None)
        qualified_lower_loader(backtest.load_repair)
        return certificate_class(catalog['event'],catalog['market_source'],codec,codec.native,
                                 mixed=mixed,inherited_root=legacy_data.HERE)
    namespace['joint_certificate']=joint
    old_events=namespace['event_rows']
    def event_rows(where,rows):
        previous,resolutions=old_events(where,rows)
        added,extra=added_permissions(where,rows,catalog,cp,permissions)
        need(not (set(previous)&set(added)),'P07_ABMD_DISJOINT_ORIGINAL_AND_NEW_EVENT_PERMISSIONS')
        return dict(previous,**added),[*resolutions,*[dict(v,bounded_model='ABMD') for v in extra]]
    namespace['event_rows']=event_rows
    def resolution_counts_valid(resolutions,current):
        old=[v for v in resolutions if v.get('bounded_model')!='ABMD']
        added=[v for v in resolutions if v.get('bounded_model')=='ABMD']
        return len(old)==1 and len(added)==(1 if current['source_cursor']>=DAY else 0)
    namespace['resolution_counts_valid']=resolution_counts_valid
    original_seed=namespace['retained_seed']
    def seed(where,actual,selected,p):
        if seed_bridge is None or len(actual['repairs'])==23:return original_seed(where,actual,selected,p)
        parent,hashes,rows,qualification=seed_bridge
        checked=origin.verify(where,actual,catalog)
        need(actual['source_cursor']==parent['source_cursor'] and actual['completed']==parent['completed']
             and actual['run']['state_sha256']==parent['run']['state_sha256']==rows[-1]['next_state_sha256']
             and len(rows)==784 and checked['parent']==parent,
             'P07_ABMD_ACTUAL_NEUTRAL_BRIDGE_OF_ALREADY_VERIFIED784_SEED')
        from system_campaign_financial_branches import encoded
        raw=b''.join(encoded(row)+b'\n' for row in rows)
        need(dict(bytes=len(raw),sha256=sha(raw))==models.plan()['committed_certificate_prefix'],
             'P07_ABMD_LITERAL_PRIOR784_BYTES_NO_PROOF_REPLAY')
        return hashes,rows,qualification
    namespace['retained_seed']=seed
    return SimpleNamespace(**namespace)
