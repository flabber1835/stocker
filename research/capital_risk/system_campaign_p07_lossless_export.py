"""Explicit, reversible duplicate representation at the unchanged host seal seam."""
import ast,hashlib,json,os,stat,tempfile
from pathlib import Path,PurePosixPath

HERE=Path(__file__).parent
ROOT='d9c73a5ceebdc806feeae4338034626c0c3b4aef42309f3849d69c20cfbf8f7b'
TEMPLATE='P07-codec-copy-inventory-template.json'
TEMPLATE_SHA='ea8f11744aaa90ad6475c78b333d52b17c3f9b5b1cc878538c1db3d72c3cd8e1'
RECEIPT='p07-lossless-codec-representation.json'
PREFIXES=('parent-preflight/','stopped-review/additional-review-codec-retention/')
SEAL_SHA='96c17b613c875174f5be9582ce48b2a18fdb9266a95d677ee7dd6fb7f61dbd0a'
FIELD='selected_p07_lossless_export'

def need(value,label):
    if not value:raise ValueError('P07_LOSSLESS_'+label)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def pin(path):
    h=hashlib.sha256();size=0
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024**2),b''):size+=len(chunk);h.update(chunk)
    return dict(bytes=size,sha256=h.hexdigest())
def safe_name(value):
    need(type(value) is str and value and value!='.' and '\\' not in value and ':' not in value,'SAFE_RELATIVE_NAME')
    p=PurePosixPath(value)
    need(not p.is_absolute() and not any(v in ('.','..') for v in p.parts) and p.as_posix()==value,'SAFE_RELATIVE_NAME')
    return value
def linked(path,info=None):
    path=Path(path);info=info or path.lstat()
    return (stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&0x400)
            or (hasattr(path,'is_junction') and path.is_junction()))
def walk(root):
    """Never traverse a symlink, reparse point or junction."""
    stack=[Path(root)]
    while stack:
        path=stack.pop();info=path.lstat();yield path,info
        if stat.S_ISDIR(info.st_mode) and not linked(path,info):
            with os.scandir(path) as entries:stack.extend(sorted((Path(v.path) for v in entries),reverse=True))
def diagnostics(root):
    files=total=links=special=0
    for path,info in walk(root):
        if linked(path,info):links+=1
        elif stat.S_ISREG(info.st_mode):files+=1;total+=info.st_size
        elif not stat.S_ISDIR(info.st_mode):special+=1
    complete=links==0 and special==0
    return dict(schema='research.P07-safe-export-bound-diagnostics/1',file_count=files,logical_bytes=total,
        symlink_or_reparse_count=links,special_file_count=special,member_bound_passed=files<5000 if complete else None,
        byte_bound_passed=total<=1024**3 if complete else None,symlink_bound_passed=links==0,
        size_and_member_measurement_complete=complete,unsafe_link_target_stats_read=False,
        financial_values_included=False,filenames_included=False,credentials_included=False)
def safe_diagnostics(root,reader=None):
    try:return dict((diagnostics if reader is None else reader)(root),diagnostic_status='MEASURED')
    except Exception:
        return dict(schema='research.P07-safe-export-bound-diagnostics/1',diagnostic_status='UNKNOWN',
            diagnostic_failure='TRAVERSAL_FAILED',file_count=None,logical_bytes=None,
            symlink_or_reparse_count=None,special_file_count=None,member_bound_passed=None,
            byte_bound_passed=None,symlink_bound_passed=None,size_and_member_measurement_complete=False,
            unsafe_link_target_stats_read=False,financial_values_included=False,filenames_included=False,
            credentials_included=False)
def inventory(root):
    root=Path(root)
    need(root.is_dir() and not linked(root),'OWNED_REAL_ROOT')
    files={};dirs={}
    for path,info in walk(root):
        need(not linked(path,info),'NO_LINKS_OR_REPARSE_POINTS')
        need(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),'NO_SPECIAL_FILES')
        need(not hasattr(os,'getuid') or info.st_uid==os.getuid(),'OWNED_ALL_MEMBERS')
        name=path.relative_to(root).as_posix()
        if stat.S_ISDIR(info.st_mode):dirs[name]=dict(mode=stat.S_IMODE(info.st_mode),atime_ns=info.st_atime_ns,mtime_ns=info.st_mtime_ns)
        else:
            need(info.st_nlink==1,'NO_HARDLINKS')
            safe_name(name);files[name]=pin(path)
    return files,dirs
def template():
    raw=(HERE/TEMPLATE).read_bytes();need(sha(raw)==TEMPLATE_SHA,'EXACT_FIN33793_TEMPLATE')
    value=json.loads(raw)
    need(value['root_admission_sha256']==ROOT and len(value['files'])==93
         and sum(v['bytes'] for v in value['files'].values())==216932007,'EXACT_FIN337_TEMPLATE_SCOPE')
    return value['files']
def allowed_candidates(template_files):
    result={}
    for name,value in template_files.items():
        safe_name(name);source=safe_name(value['retained_relative'])
        need(not source.startswith(PREFIXES) and source!=RECEIPT,'ONLY_PHYSICAL_ROOT_ORIGINAL_SOURCES')
        expected={k:value[k] for k in ('bytes','sha256')}
        for prefix in PREFIXES:result[prefix+name]=dict(expected,source=source)
    return result
def validate_stops(stops):
    need(type(stops) is list and len(stops)>=2,'ALL_ACTUAL_WRITERS_TRACKED')
    need([s['role'] for s in stops][:2]==['preflight','economic']
         and len({s['role'] for s in stops})==len(stops) and set(s['role'] for s in stops)<=set(('preflight','economic','review')),'EXACT_ACTUAL_WRITER_ORDER')
    for record in stops:
        value=record['result'];inspection=record['inspection']
        need(record['returned'] is True and value['stopped'] is True and type(value['exit_code']) is int
             and type(value['oom_killed']) is bool and inspection['State']['Running'] is False
             and inspection['State']['ExitCode']==value['exit_code']
             and inspection['State']['OOMKilled'] is value['oom_killed']
             and record['inspection_sha256']==digest(inspection),'ALL_ATTEMPTED_WRITERS_POSITIVELY_STOPPED')
    return [dict(role=v['role'],result=v['result'],inspection_sha256=v['inspection_sha256']) for v in stops]
def plan(root,stops,template_files=None):
    root=Path(root).absolute()
    need(all(not linked(path) for path in [root,*root.parents]),'NO_ROOT_OR_ANCESTOR_LINKS')
    root=root.resolve();stop_proofs=validate_stops(stops)
    before,dirs=inventory(root);need(RECEIPT not in before,'FRESH_REPRESENTATION_NAMESPACE')
    for record in stops:
        inspection_name={'preflight':'parent-preflight/worker-inspect.json','economic':'worker-inspect.json','review':'stopped-review/worker-inspect.json'}[record['role']]
        need(inspection_name in before and digest(json.loads((root/inspection_name).read_bytes()))==record['inspection_sha256'],
             'ALL_ACTUAL_STOP_INSPECTIONS_PHYSICALLY_RETAINED')
    candidates=allowed_candidates(template_files if template_files is not None else template());copies=[]
    for name,value in sorted(candidates.items()):
        if name not in before:continue
        expected={k:value[k] for k in ('bytes','sha256')};source=value['source']
        need(source in before and before[source]==before[name]==expected,'EVERY_COPY_EQUALS_PINNED_PHYSICAL_ORIGINAL')
        need((root/name).read_bytes()==(root/source).read_bytes(),'INDEPENDENT_FULL_BYTE_EQUALITY')
        info=(root/name).stat()
        copies.append(dict(name=name,source=source,retained_source_path=(root/source).as_posix(),**expected,
            mode=stat.S_IMODE(info.st_mode),atime_ns=info.st_atime_ns,mtime_ns=info.st_mtime_ns))
    need(copies,'AT_LEAST_ONE_REAL_DUPLICATE')
    names={v['name'] for v in copies};physical={k:v for k,v in before.items() if k not in names}
    receipt=dict(schema='research.P07-lossless-codec-representation/1',root_admission_sha256=ROOT,
        template_sha256=TEMPLATE_SHA,representation='EXACT_PER_FILE_COPY_EQUIVALENCE',financial_authority=False,
        retained_source_root=root.as_posix(),
        original_financial_files_deleted=False,export_cap_changed=False,writer_stops=stop_proofs,copies=copies,
        before_inventory=before,physical_original_inventory=physical,expanded_original_inventory=before,
        before_inventory_sha256=digest(before),physical_original_inventory_sha256=digest(physical),
        represented_bytes=sum(v['bytes'] for v in copies),represented_file_count=len(copies))
    return dict(root=root,before=before,dirs=dirs,receipt=receipt)
def restore_metadata(root,dirs):
    for name,value in sorted(dirs.items(),key=lambda x:len(PurePosixPath(x[0]).parts),reverse=True):
        path=root if name=='.' else root/name
        os.chmod(path,value['mode']);os.utime(path,ns=(value['atime_ns'],value['mtime_ns']))
def seal_represented(root,original_seal,args,kwargs,stops,*,template_files=None,observe=None,move=os.replace):
    """Move only verified copies to an owned rollback directory; always restore."""
    p=plan(root,stops,template_files);root=p['root'];receipt=p['receipt'];copies=receipt['copies']
    backup=Path(tempfile.mkdtemp(prefix='p07-lossless-export-rollback-',dir=root.parent)).resolve()
    need(backup.parent==root.parent and not backup.is_relative_to(root) and not linked(backup),'OWNED_OUTSIDE_INPUT_BACKUP')
    moved=[];created=[];receipt_created=False;result=None
    try:
        # Finite permissions apply only to already validated copied namespaces.
        parents={path for v in copies for path in (root/v['name']).parents if path!=root and path.is_relative_to(root)}
        for path in parents:
            need(path.relative_to(root).parts[0] in ('parent-preflight','stopped-review'),'ONLY_OWNED_COPY_NAMESPACE_PERMISSIONS')
            os.chmod(path,path.stat().st_mode|stat.S_IWUSR|stat.S_IXUSR)
        for index,record in enumerate(copies):
            src=root/record['name'];dst=backup/str(index)
            need(pin(src)==pin(root/record['source'])=={k:record[k] for k in ('bytes','sha256')},'RECHECK_COPY_AND_ORIGINAL_BEFORE_MOVE')
            try:move(src,dst)
            except Exception:
                if dst.is_file() and not src.exists():moved.append((record,dst))
                raise
            moved.append((record,dst))
        with (root/RECEIPT).open('xb') as stream:receipt_created=True;stream.write(encoded(receipt));stream.flush();os.fsync(stream.fileno())
        actual,_=inventory(root);need(actual==dict(p['receipt']['physical_original_inventory'],**{RECEIPT:pin(root/RECEIPT)}),'EXACT_PHYSICAL_REPRESENTATION_BEFORE_SEAL')
        if observe:observe(safe_diagnostics(root))
        result=original_seal(root,*args,**kwargs)
        need(inventory(root)[0]==actual,'ORIGINAL_SEAL_READ_ONLY_NO_SOURCE_MUTATION')
    finally:
        # Failure leaves originals and every unique failure record in place.
        # Backups are never recursively deleted, including on rollback failure.
        rollback_errors=[]
        if receipt_created:
            try:(root/RECEIPT).unlink()
            except Exception as exc:rollback_errors.append(type(exc).__name__)
        for record,dst in reversed(moved):
            try:
                need(not (root/record['name']).exists(),'NO_REPLACEMENT_AT_ROLLBACK_PATH')
                os.replace(dst,root/record['name'])
            except Exception as exc:rollback_errors.append(type(exc).__name__)
        try:restore_metadata(root,p['dirs'])
        except Exception as exc:rollback_errors.append(type(exc).__name__)
        if not rollback_errors:
            need(inventory(root)[0]==p['before'],'WHOLE_EXACT_ORIGINAL_TREE_RESTORED')
            for record in copies:
                path=root/record['name']
                os.chmod(path,record['mode']);os.utime(path,ns=(record['atime_ns'],record['mtime_ns']))
            restore_metadata(root,p['dirs'])
            backup.rmdir()
        need(not rollback_errors,'ROLLBACK_FAILED_BACKUPS_PRESERVED')
    return result
def logical_members(member,physical_manifest,*,template_files=None):
    """Verify explicit representation and return an exact logical DATA reader."""
    need(RECEIPT in physical_manifest,'AUTHENTICATED_REPRESENTATION_RECEIPT_REQUIRED')
    def physical(name):
        need(name in physical_manifest,'AUTHENTICATED_PHYSICAL_MEMBER_REQUIRED');raw=member(name)
        need(dict(bytes=len(raw),sha256=sha(raw))==physical_manifest[name],'PHYSICAL_MEMBER_AT_USE');return raw
    receipt=json.loads(physical(RECEIPT));before=receipt['before_inventory'];remaining=receipt['physical_original_inventory']
    need(receipt['schema']=='research.P07-lossless-codec-representation/1'
         and receipt['root_admission_sha256']==ROOT and receipt['template_sha256']==TEMPLATE_SHA
         and receipt['representation']=='EXACT_PER_FILE_COPY_EQUIVALENCE'
         and receipt['financial_authority'] is receipt['original_financial_files_deleted'] is receipt['export_cap_changed'] is False,
         'EXACT_REPRESENTATION_SCOPE_NO_FINANCIAL_AUTHORITY')
    need(receipt['before_inventory_sha256']==digest(before) and receipt['physical_original_inventory_sha256']==digest(remaining)
         and receipt['expanded_original_inventory']==before,'FULL_EXACT_LOGICAL_INVENTORY_COMMITMENTS')
    need(set(physical_manifest)==set(remaining)|{RECEIPT} and all(physical_manifest[k]==v for k,v in remaining.items()),'COMPLETE_PHYSICAL_MANIFEST_NO_PREFIX_EXEMPTION')
    roles=[v['role'] for v in receipt['writer_stops']]
    need(roles[:2]==['preflight','economic'] and len(roles)==len(set(roles)) and set(roles)<=set(('preflight','economic','review')),'EXACT_EXPORTED_WRITER_PROOF_ORDER')
    for record in receipt['writer_stops']:
        inspection_name={'preflight':'parent-preflight/worker-inspect.json','economic':'worker-inspect.json','review':'stopped-review/worker-inspect.json'}[record['role']]
        inspection=json.loads(physical(inspection_name));value=record['result']
        need(value['stopped'] is True and type(value['exit_code']) is int and type(value['oom_killed']) is bool
             and inspection['State']['Running'] is False and inspection['State']['ExitCode']==value['exit_code']
             and inspection['State']['OOMKilled'] is value['oom_killed'] and digest(inspection)==record['inspection_sha256'],
             'EXPORTED_ACTUAL_INSPECTIONS_POSITIVELY_STOPPED')
    candidates=allowed_candidates(template_files if template_files is not None else template());aliases={}
    for record in receipt['copies']:
        name=safe_name(record['name']);source=safe_name(record['source']);need(name not in aliases and name in candidates,'FINITE_UNIQUE_COPY_NAMES')
        need(record['retained_source_path']==(PurePosixPath(receipt['retained_source_root'])/source).as_posix(),
             'EXACT_REAL_RETAINED_PATH_PROVENANCE')
        expected={k:record[k] for k in ('bytes','sha256')}
        need(candidates[name]==dict(expected,source=source) and source in remaining
             and name not in remaining and before.get(name)==before.get(source)==remaining[source]==expected,'EXACT_PER_FILE_SOURCE_EQUIVALENCE_NO_CYCLES')
        need(dict(bytes=len(physical(source)),sha256=sha(physical(source)))==expected,'EVERY_RETAINED_SOURCE_AUTHENTIC_AT_USE')
        aliases[name]=source
    need(set(before)==set(remaining)|set(aliases) and receipt['represented_file_count']==len(aliases)
         and receipt['represented_bytes']==sum(before[k]['bytes'] for k in aliases),'COMPLETE_BEFORE_PHYSICAL_EXPANDED_EQUIVALENCE')
    def logical(name):
        need(name in before or name==RECEIPT,'EXACT_LOGICAL_MEMBER_NAME')
        raw=physical(aliases.get(name,name));expected=physical_manifest[RECEIPT] if name==RECEIPT else before[name]
        need(dict(bytes=len(raw),sha256=sha(raw))==expected,'EXACT_LOGICAL_BYTES_AT_USE');return raw
    logical.names=set(before)|{RECEIPT};logical.representation=receipt
    return logical
