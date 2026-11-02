"""Synthetic AES-GCM/all-member transport and exact metadata API tests."""
import ast
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_reference_admit as admit
from p01_iac_reference_evidence import reference_spec,COMPONENT,ZERO
from seal import MAGIC


def artifact(tmp_path,kind=None):
    files={n:b'opaque static control' for n in admit.CONTROL}
    files.update({COMPONENT:b'opaque synthetic component never decoded',ZERO:b'opaque synthetic zero never decoded',
        'qualification-failure/fast/book/watch.jsonl':b'{incomplete opaque raw tail'})
    inventory={n:dict(bytes=len(v),sha256=admit.sha(v)) for n,v in files.items()}
    if kind=='omitted':inventory['qualification-failure/fast/book/opaque.json']=dict(bytes=3,sha256=admit.sha(b'old'))
    if kind=='hash':files['qualification-failure/fast/book/watch.jsonl']=b'x'*len(files['qualification-failure/fast/book/watch.jsonl'])
    if kind=='unsafe':
        files['../forbidden.json']=b'opaque';inventory['../forbidden.json']=dict(bytes=6,sha256=admit.sha(b'opaque'))
    origin=dict(admit.ORIGIN,protocol_sha256='a'*64,stage='campaign-p01-iac-unit-fixture-qualification')
    manifest=dict(schema='research.full-system-output/1',stage=origin['stage'],arm='P01',run_id=str(origin['run_id']),head=origin['head'],
        request_sha256=origin['request_sha256'],protocol_sha256=origin['protocol_sha256'],compression='TAR_GZIP_V1',members=inventory)
    if kind=='identity':manifest['head']='b'*40
    raw=(json.dumps(manifest,sort_keys=True)+'\n').encode();body=io.BytesIO()
    with tarfile.open(fileobj=body,mode='w') as tar:
        for name,data in [('manifest.json',raw),*files.items()]:
            info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
    nonce=b'0'*12;header=MAGIC+nonce;key=b'x'*32
    cipher=header+AESGCM(key).encrypt(nonce,gzip.compress(body.getvalue(),mtime=0),header)
    if kind=='gcm':cipher=cipher[:-1]+bytes([cipher[-1]^1])
    asset=dict(name='synthetic.tar.crseal',bytes=len(cipher),sha256=admit.sha(cipher),manifest_sha256=admit.sha(raw),compression='TAR_GZIP_V1')
    origin['authenticated_manifest']=dict(bytes=len(raw),sha256=admit.sha(raw),members_count=len(inventory),
        raw_members_bytes=sum(v['bytes'] for v in inventory.values()),inventory_sha256=admit.digest(inventory))
    spec=dict(origin=origin,approved_members={n:inventory[n] for n in (COMPONENT,ZERO)})
    path=tmp_path/'synthetic.zip'
    with zipfile.ZipFile(path,'x') as z:z.writestr(asset['name'],cipher)
    return path,asset,key,spec


def extract(tmp_path,kind=None,fn=None):
    path,asset,key,spec=artifact(tmp_path,kind)
    with zipfile.ZipFile(path) as z:return (fn or admit.extract_selected)(z,asset,key,tmp_path/'selected',spec)


def test_all_opaque_members_authenticated_but_only_approved_two_materialized(tmp_path):
    value=extract(tmp_path)
    files={p.relative_to(tmp_path/'selected').as_posix() for p in (tmp_path/'selected').rglob('*') if p.is_file()}
    assert files=={COMPONENT,ZERO} and value['members']==8
    assert value['controls']['request.json']==b'opaque static control'
    assert value['manifest']['members']['qualification-failure/fast/book/watch.jsonl']['bytes']>0


@pytest.mark.parametrize('kind',['omitted','hash','unsafe','identity','gcm'])
def test_whole_inventory_gcm_path_and_identity_fail_closed(tmp_path,kind):
    with pytest.raises(Exception):extract(tmp_path,kind)
    assert not (tmp_path/'forbidden.json').exists()


def test_full_first_gcm_authentication_precedes_any_plaintext_metadata_parse(tmp_path,monkeypatch):
    calls=[];original=admit.plain
    def record(raw):calls.append(raw);return original(raw)
    monkeypatch.setattr(admit,'plain',record)
    with pytest.raises(Exception):extract(tmp_path,'gcm')
    assert calls==[] and not (tmp_path/'selected').exists()


def test_complete_inventory_guard_removal_accepts_omitted_opaque_member_falsifier(tmp_path):
    first=tmp_path/'strict';first.mkdir()
    with pytest.raises(ValueError):extract(first,'omitted')
    fn=next(n for n in ast.parse(Path(admit.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='extract_selected')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(x,ast.Constant)
        and x.value=='REFERENCE_ADMIT_NO_OMITTED_OR_EXTRA_OLD_BYTES' for x in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(admit))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-whole-inventory>','exec'),ns)
    second=tmp_path/'falsified';second.mkdir();value=extract(second,'omitted',ns['extract_selected'])
    assert value['members']==8 and len(value['manifest']['members'])==9


def test_exact_safe_public_spec_and_unexpected_private_key_refuse():
    value=reference_spec();assert admit.check_spec(value)==value
    for mutate in (lambda v:v.update(private_book={}),lambda v:v['origin'].update(raw_quote='private'),
        lambda v:v['origin']['actual_worker_stop']['metadata'].update(exit_code=0),lambda v:v.update(financial_authority=True)):
        wrong=deepcopy(value);mutate(wrong)
        with pytest.raises(ValueError):admit.check_spec(wrong)


def test_unbound_spec_refuses_before_host_or_network_authority(tmp_path,monkeypatch):
    monkeypatch.setattr(admit.crypto,'hosted_destination',lambda *a:pytest.fail('host authority before exact public spec'))
    with pytest.raises(ValueError):admit.admit_reference(tmp_path,b'x'*32,dict(schema='unbound'))


def test_source_has_no_old_payload_state_decoder_or_financial_runtime_calls():
    tree=ast.parse(Path(admit.__file__).read_bytes());calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    assert not calls & {'gzip.decompress','runtime.restore','SessionState.from_dict','Ledger.from_dict','backtest.main'}
    assert 'crypto.authenticate' in calls and 'crypto.AuthenticatedStream' in calls
