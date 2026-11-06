import ast,json,os,sys
from copy import deepcopy
from pathlib import Path
import pytest
D=Path('C:/GitHub/stocker/.codex-tmp/p05-ctxs-own1175-20261106');C=Path(__file__).parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE18_V2_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_p05_remaining_source_preparation_v2 as prep
from system_campaign_financial_partial import root_spec
@pytest.fixture(scope='module')
def actual():
    r=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial326-source-snapshot/capture-P05-13479382405-001')
    manifest=json.loads((r/'authenticated-manifest.json').read_bytes())['members'];root=r/'verified-output'
    if os.name=='nt' and not str(root).startswith('\\\\?\\'):root=Path('\\\\?\\'+str(root.resolve()))
    assert all((root/n).is_file() for n in manifest)
    spec=root_spec('P05',prep.original.data.own.ROOT);allowed=prep.inherited(root,spec)
    # DATA union: exact actual19 source names plus real prior preflight metadata.
    # No file is copied and no future worker output is being claimed.
    provenance={n:n for n in allowed}
    provenance.update({n.removeprefix('parent-preflight/'):n for n in manifest if n.startswith('parent-preflight/') and not n.removeprefix('parent-preflight/').startswith('book/')})
    names=set(provenance)
    def member(n):
        name=provenance[n];raw=(root/name).read_bytes()
        assert dict(bytes=len(raw),sha256=prep.sha(raw))==manifest[name]
        return raw
    return allowed,names,member
def test_six_neutral_and19_original_input_resources_are_exactly_allowed(actual):
    allowed,names,member=actual
    assert len(allowed)==25 and set(allowed)<=names
    assert prep.output_members(names,member,allowed)==sorted(names)
@pytest.mark.parametrize('name',['book/new.bin','input-adoption/new.bin','new-neutral/checkpoint.json.gz','new-neutral/proof.json'])
def test_any_new_canonical_namespace_still_refuses(actual,name):
    allowed,names,member=actual
    with pytest.raises(ValueError,match='NO_NEW_CANONICAL'):prep.output_members(names|{name},member,allowed)
def test_changed_real_inherited_resource_bytes_are_refused(actual):
    allowed,names,member=actual;name=next(iter(allowed))
    with pytest.raises(ValueError,match='EXACT_INHERITED_CANONICAL_LOOKING_BYTES'):
        prep.output_members(names,lambda n:member(n)+b'corrupt DATA falsifier' if n==name else member(n),allowed)
def test_inherited_byte_guard_removal_is_meaningful(actual,monkeypatch):
    allowed,names,member=actual;name=next(iter(allowed));reader=lambda n:member(n)+b'corrupt DATA falsifier' if n==name else member(n)
    with pytest.raises(ValueError):prep.output_members(names,reader,allowed)
    need=prep.need;monkeypatch.setattr(prep,'need',lambda v,label:None if label=='P05_SOURCE18_V2_EXACT_INHERITED_CANONICAL_LOOKING_BYTES' else need(v,label))
    assert prep.output_members(names,reader,allowed)==sorted(names)
def test_missing_inherited_metadata_does_not_get_relabelled(actual):
    allowed,names,member=actual
    with pytest.raises(ValueError,match='NO_OMISSION'):prep.output_members(names-{next(iter(allowed))},member,allowed)
def test_extra_or_relocated_allowance_cannot_change_original_six_names(actual):
    allowed,names,member=actual;bad=deepcopy(allowed);pin=bad.pop(next(iter(bad)));bad['relocated/checkpoint.json.gz']=pin
    with pytest.raises(ValueError,match='ONLY_SIX_OLD_NEUTRAL_AND19_COMMITTED_INPUT_NAMES'):prep.output_members(names,member,bad)
def test_source_v1_package_remains_closed_and_byte_identical():
    raw=(D/'P05-retained18-source-preparation-qualification.json').read_bytes();assert prep.sha(raw)==prep.V1_SHA
    q=json.loads(raw)
    for name,pin in q['files'].items():assert dict(bytes=(D/name).stat().st_size,sha256=prep.sha((D/name).read_bytes()))==pin
def test_all_whole_legacy_functions_are_bound_without_body_edits():
    raw=Path(prep.__file__).read_bytes();tree=ast.parse(raw)
    calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
    assert calls.count('FunctionType')==3
    assert not any(n.endswith(('.advance','.restore','.write_checkpoint','.main')) for n in calls)
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
