"""FIN324 actual immutable metadata receipt regression; no checkpoint copying."""
import ast,json,sys
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_ARCHIVE_RECEIPT_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(1,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
sys.path.insert(2,'C:/GitHub/stocker/.codex-tmp/shared-abmd-bounded-20261105')
import system_campaign_p07_abmd_legacy as data

ROOT=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial324-source-snapshot/capture-P07-13477298284-001')
NAME='uncertainty-event-archive-preservation.json'
def read(path):return Path('\\\\?\\'+str(path.resolve())).read_bytes()

@pytest.fixture(scope='module')
def actual():
    manifest=json.loads(read(ROOT/'authenticated-manifest.json'))['members']
    def member(name):
        raw=read(ROOT/'verified-output'/name)
        assert dict(bytes=len(raw),sha256=data.sha(raw))==manifest[name];return raw
    raw=member(NAME);trace=member('worker.log').decode()
    assert "FileExistsError: [Errno 17] File exists: '/out/"+NAME+"'" in trace
    assert '<whole-original-archive-preserver-exact-idempotent-self-source>' in trace
    assert "line 19, in save" in trace
    value=json.loads(raw)
    assert value['same_name_and_bytes'] is True and value['checkpoint_bytes_or_name_changed'] is False
    assert value['new_checkpoint_or_alias_created'] is False and value['financial_sessions_advanced']==0
    # Read the existing actual producer gzip only; do not copy/write/restore it.
    archive=member(value['preserved_as']);assert data.sha(archive)==value['file_sha256']
    return raw,value

def test_original_exclusive_save_reproduces_actual_metadata_failure(actual,tmp_path):
    from full_system_benchmark import save
    raw,value=actual;path=tmp_path/NAME;path.write_bytes(raw)
    with pytest.raises(FileExistsError):save(path,value)
    assert path.read_bytes()==raw

def test_exact_existing_actual_receipt_is_verified_without_rewrite(actual,tmp_path):
    raw,value=actual;path=tmp_path/NAME;path.write_bytes(raw);before=path.stat()
    data.save_archive_receipt(path,value);after=path.stat()
    assert path.read_bytes()==raw and before.st_mtime_ns==after.st_mtime_ns and before.st_ino==after.st_ino

def test_fresh_metadata_keeps_original_exclusive_creation_then_exact_reuse(actual,tmp_path):
    raw,value=actual;path=tmp_path/NAME
    data.save_archive_receipt(path,value)
    fresh=path.read_bytes()
    # The unchanged original text saver uses native line endings. Production is
    # hosted Linux; Windows DATA tests prove other bytes are refused unchanged.
    assert fresh.decode().replace('\r\n','\n')==raw.decode()
    if fresh==raw:data.save_archive_receipt(path,value)
    else:
        with pytest.raises(ValueError):data.save_archive_receipt(path,value)
    assert path.read_bytes()==fresh

@pytest.mark.parametrize('change',['value','whitespace','path'])
def test_changed_metadata_or_unqualified_path_refused_without_overwrite(actual,tmp_path,change):
    raw,value=actual;value=dict(value);path=tmp_path/NAME;path.write_bytes(raw)
    if change=='value':value['file_sha256']='0'*64
    elif change=='whitespace':path.write_bytes(raw+b' ')
    else:path=tmp_path/'OTHER.json';path.write_bytes(raw)
    before=path.read_bytes()
    with pytest.raises(ValueError):data.save_archive_receipt(path,value)
    assert path.read_bytes()==before

def test_removing_exact_existing_byte_guard_accepts_altered_receipt(actual,tmp_path):
    raw,value=actual;path=tmp_path/NAME;path.write_bytes(raw+b' ')
    fn=data.legacy_data.original.function(Path(data.__file__).read_bytes(),'save_archive_receipt')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='P07_ABMD_EXISTING_ARCHIVE_RECEIPT_EXACT_BYTES_NO_OVERWRITE' for v in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-metadata-byte-guard-only>','exec'),scope)
    with pytest.raises(ValueError):data.save_archive_receipt(path,value)
    assert scope['save_archive_receipt'](path,value) is None

def test_original_archive_resolver_and_preserver_guards_remain_whole():
    raw=(Path(data.legacy_data.HERE)/'system_campaign_uncertainty_archive.py').read_bytes()
    assert data.sha(raw)==data.ARCHIVE_SHA
    tree=data.archive_tree(raw)
    assert 'same_existing_archive(actual, target, proof)' in ast.unparse(tree)
    assert "sha(target.read_bytes()) == proof['file_sha256']" in ast.unparse(tree)
    resolver=data.archive_resolver_tree(raw)
    assert 'UNCERTAINTY_ARCHIVE_CANONICAL_PRODUCER_NAME_AND_OUTER_DIGEST' in ast.unparse(resolver)
    assert 'UNCERTAINTY_ARCHIVE_UNIQUE_EXACT_PRE_EVENT_STATE_AND_INPUT' in ast.unparse(resolver)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
