"""Pure artifact/input/tail guards; no historical financial state transitions."""
import ast,copy,io,json,os,zipfile
from dataclasses import asdict,make_dataclass,replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest
from cryptography.exceptions import InvalidTag
from seal import EncryptWriter
import system_campaign_facts as facts
import system_campaign_factual_admit as admission
from system_campaign_factual_run import preserve_tails

HERE=Path(__file__).resolve().parents[1]


def test_loader_refuses_local_before_network_or_filesystem_mutation(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    monkeypatch.setattr(admission.subprocess,'run',lambda *a,**kw:pytest.fail('network reached'))
    target=tmp_path/'forbidden'
    with pytest.raises(ValueError,match='REFUSED_CONTEXT_GITHUB_ACTIONS'):admission.admit({},target,b'x'*32)
    assert not target.exists()
    # Removing the context guard still cannot escape the independent destination
    # and POSIX/capacity boundary; no private archive is constructed in this test.
    monkeypatch.setattr(admission,'check_context',lambda env:None)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    with pytest.raises(ValueError,match='HOSTED_FACTUAL_DESTINATION_CAPACITY'):admission.hosted_destination(target)


def test_stream_authenticates_gcm_and_refuses_modified_ciphertext():
    output=io.BytesIO();writer=EncryptWriter(output,b'x'*32);writer.write(b'synthetic marker only');writer.finish();raw=output.getvalue()
    import hashlib
    def archive(value):
        result=io.BytesIO()
        with zipfile.ZipFile(result,'w') as z:z.writestr('marker.crseal',value)
        result.seek(0);return zipfile.ZipFile(result)
    spec={'name':'marker.crseal','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    with archive(raw) as z:
        header,tag=admission.authenticate(z,spec,b'x'*32)
        with z.open('marker.crseal') as source:
            stream=admission.AuthenticatedStream(source,spec,b'x'*32,header,tag)
            assert stream.read(100)==b'synthetic marker only' and stream.read(100)==b'' and stream.done
    changed=bytearray(raw);changed[21]^=1
    with archive(changed) as z:
        with pytest.raises(InvalidTag):admission.authenticate(z,spec,b'x'*32)


def test_catalog_compiler_commitments_and_mutation_refuse():
    c=facts.FactualInputs(HERE/'system-campaign-factual-catalog.json')
    r=SimpleNamespace(source_evidence=[SimpleNamespace(**v) for v in c.evidence()],earliest_affected_session='2017-08-09',_resume_session='2017-07-17')
    assert c._bound(r)
    r._resume_session='2017-08-09'
    with pytest.raises(ValueError,match='ALL_CORRECTIONS_FUTURE'):c._bound(r)
    r._resume_session='2017-07-17';r.source_evidence[1].sha256='0'*64
    with pytest.raises(ValueError,match='CATALOG_COMPILER_COMMITMENTS'):c._bound(r)
    r.source_evidence=[SimpleNamespace(**v) for v in c.evidence()];c.catalog['fnf']['cash_proxy_per_parent']='0'
    with pytest.raises(ValueError,match='CATALOG_UNCHANGED'):c._bound(r)


def test_public_catalog_contains_no_private_quote_rows_or_prices(tmp_path,monkeypatch):
    c=facts.FactualInputs(HERE/'system-campaign-factual-catalog.json')
    assert c.catalog['private_quote_hydration_required']
    assert not {'parent_bar','child_bar','cash_proxy_per_parent'} & set(c.catalog['fnf'])
    assert all(set(v)=={'term_sha256','source_row_id'} for v in c.catalog['fnf']['native'])
    assert c.catalog['fnf']['added']['cash_in_lieu_price'] is None
    assert all(v['added']['cash_in_lieu_price_per_delivered_share'] is None for v in c.catalog['terms'] if v['proxy'])
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED_PRIVATE_FACT_HYDRATION_ONLY'):c.hydrate(tmp_path/'no-private-data.json')
    assert not (tmp_path/'no-private-data.json').exists()


def test_reused_pure_input_body_suppresses_double_cash_and_keeps_other_fields():
    path=os.environ.get('STOCKER_FROZEN_RESEARCH_SOURCE')
    if not path:pytest.skip('Frozen private input-function bytes are qualified inside each hosted job')
    raw=(Path(path)/'research/pooled_vacancy_funding/repair.py').read_bytes()
    fn=facts.compile_input_function(raw,{'_session':lambda v:v,'_digest':facts.digest,'asdict':asdict,'replace':replace,'Decimal':Decimal})
    private=os.environ.get('STOCKER_PRIVATE_FACT_CATALOG')
    if not private:pytest.skip('Private quote fixture is never copied into the public repository')
    catalog=json.loads(Path(private).read_bytes())['fnf']
    Bar=make_dataclass('Bar',[(k,object) for k in catalog['parent_bar']],frozen=True)
    Spin=make_dataclass('Spin',[(k,object) for k in catalog['native'][0]['native']],frozen=True)
    Packet=make_dataclass('Packet',[('day',str),('bars',tuple),('spins',tuple)],frozen=True)
    original=Packet('2017-10-02',(Bar(**catalog['parent_bar']),Bar(**catalog['child_bar'])),tuple(Spin(**v['native']) for v in catalog['native']))
    added=Spin(**catalog['added'])
    repair=SimpleNamespace(_resume_session='2017-07-17',earliest_affected_session='2017-10-02',
        suppress=[SimpleNamespace(term_sha256=v['term_sha256']) for v in catalog['native']],
        add=[SimpleNamespace(cash_in_lieu_price='43.0',terms=lambda:added)],parent_bar_sha256=catalog['parent_bar_sha256'],
        child_bar_sha256=catalog['child_bar_sha256'],cash_proxy_per_parent='13.501')
    before=asdict(original);changed=fn(original,repair)
    assert asdict(original)==before and changed.spins==(added,) and changed.bars[0].dividend_per_share==0.
    assert changed.bars[1] is original.bars[1]
    for bad in (replace(original,spins=original.spins[:1]),replace(original,bars=(replace(original.bars[0],raw_open=35.03),original.bars[1]))):
        with pytest.raises(ValueError):fn(bad,repair)
    # A guard-removal variant accepts the altered source row, demonstrating that
    # the source-row invariant is material, not a mirror assertion.
    node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_apply_spinoff_repair')
    guard=next(n for n in node.body if isinstance(n,ast.If) and 'suppress <=' in ast.unparse(n.test))
    node.body.remove(guard)
    for n in ast.walk(node):
        if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value in facts.IDENTITIES:n.value=facts.IDENTITIES[n.value]
    scope={'_session':lambda v:v,'_digest':facts.digest,'asdict':asdict,'replace':replace,'Decimal':Decimal}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<guard-removal>','exec'),scope)
    assert scope['_apply_spinoff_repair'](replace(original,spins=original.spins[:1]),repair).spins==(added,)


def test_exact_tail_bytes_required(tmp_path):
    raw=b'untouched historical suffix\n';p=tmp_path/'interrupted-watch-marker.jsonl';p.write_bytes(raw)
    proof={'tails_to_preserve':{'watch':{'bytes':len(raw),'sha256':facts.sha(raw)}}}
    assert preserve_tails(tmp_path,proof)['watch']['path']==p.name
    p.write_bytes(raw.replace(b'suffix',b'SUFFIX'))
    with pytest.raises(ValueError,match='EXACT_RECOVERED_TAIL'):preserve_tails(tmp_path,proof)


def test_latest_failed_qualifier_must_prove_no_new_state_or_journal_bytes(tmp_path):
    (tmp_path/'independent-review-stop').mkdir()
    (tmp_path/'independent-review-stop/core-review.json').write_text(json.dumps({'all_prefixes_verified':True,'all_daily_factors_and_chains_verified':True,'complete':False}))
    (tmp_path/'economic-worker.log').write_text('in qualify_inputs\nValueError: suppressed original spinoff differs\n')
    nested={f'book/{n}.jsonl':{'bytes':0,'sha256':facts.sha(b'')} for n in ('formation','daily','monthly','watch')}
    cp={'bytes':10,'sha256':'a'*64};inventory={**nested,**{'lineage/old-branch/'+k:v for k,v in nested.items()},'book/checkpoint.json.gz':cp}
    spec={'immutable_old_branch_inventory_sha256':facts.digest(nested),'selected_file':cp}
    admission.prove_unadvanced(spec,inventory,tmp_path)
    for path,value in (('book/watch.jsonl',{'bytes':1,'sha256':'b'*64}),('book/checkpoint.json.gz',{'bytes':10,'sha256':'c'*64}),('book/status.json',{'bytes':1,'sha256':'d'*64})):
        altered=copy.deepcopy(inventory);altered[path]=value
        with pytest.raises(ValueError):admission.prove_unadvanced(spec,altered,tmp_path)
