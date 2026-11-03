"""Pure actual628 metadata plus synthetic real GCM; no financial restoration."""
from copy import deepcopy
import ast
import io
import json
import os
import inspect
from pathlib import Path
import sys
import textwrap
import tarfile
from typing import get_args
import zipfile

from cryptography.exceptions import InvalidTag
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import p01_iac_unit_parent as parent
import seal


def spec():
    value={n:get_args(f.annotation)[0] for n,f in parent.IdentityPins.model_fields.items()}
    repairs=[dict(sha256='0'*64)]*9+[dict(sha256=parent.TENTH),dict(filename=parent.ELEVENTH+'.json',
        sha256=parent.ELEVENTH,resume_session='2020-02-04',predecessor_checkpoint_sha256=parent.ELEVENTH_ORIGINAL_PREDECESSOR)]
    value.update(schema='research.p01-own628-iac-unit-predecessor/1',selected_file=parent.GZIP,
        selected_checkpoint='book/checkpoint.json.gz',request_sha256=parent.PRIOR_SHA,request=parent.PRIOR,total_inputs=11,repairs=repairs,
        protocol_sha256=parent.PROTOCOL,stage=parent.STAGE,next_session='2020-07-01',
        source_epoch=dict(original_physical=515,successor_physical=516,original_canonical=223,successor_canonical=224,
            original_source_bindings=dict(bytes=1,sha256=parent.OLD_BINDING),successor_source_map=dict(bytes=1,sha256=parent.SOURCE_MAP),
            successor_source_map_identity_sha256=parent.MAP_IDENTITY),
        retained_checkpoint_files={'book/checkpoint.json.gz':parent.GZIP,**{f'lineage/{n}.json.gz':{} for n in range(37)}})
    return value


def capsule(tmp_path,*,protocol=parent.PROTOCOL,stage=parent.STAGE,extra=False,bad_member=False):
    payload=b'synthetic nonfinancial proof only'
    manifest=dict(schema='research.full-system-output/1',stage=stage,arm='P01',run_id=str(parent.RUN),head=parent.HEAD,
        request_sha256=parent.PRIOR_SHA,protocol_sha256=protocol,
        members={'proof.txt':dict(bytes=len(payload),sha256='0'*64 if bad_member else parent.sha(payload))})
    raw=json.dumps(manifest,sort_keys=True).encode();plain=io.BytesIO()
    with tarfile.open(fileobj=plain,mode='w:gz') as tar:
        for name,body in [('manifest.json',raw),('proof.txt',payload)]+([('extra.txt',b'x')] if extra else []):
            member=tarfile.TarInfo(name);member.size=len(body);tar.addfile(member,io.BytesIO(body))
    out=io.BytesIO();writer=seal.EncryptWriter(out,b'k'*32);writer.write(plain.getvalue());writer.finish()
    cipher=out.getvalue();path=tmp_path/'synthetic.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('proof.crseal',cipher)
    return path,dict(name='proof.crseal',bytes=len(cipher),sha256=parent.sha(cipher),manifest_sha256=parent.sha(raw))


def test_actual628_identity_projection_and_original526_bound_eleventh():
    value=spec();assert parent.check_spec(value)['measured_closes']==628
    assert value['repairs'][10]['resume_session']=='2020-02-04'


@pytest.mark.parametrize('field,value',[('outer_sha256','0'*64),('root_admission_descriptor_sha256','0'*64),
    ('qualification_state_adopted',True),('financial_predecessor_admitted',1),('current_tails_zero',1),
    ('selected_session','2020-02-04'),('next_session','2020-06-30'),('request_sha256','0'*64)])
def test_wrong_actual_authority_or_domain_refuses(field,value):
    wrong=deepcopy(spec());wrong[field]=value
    with pytest.raises(ValueError):parent.check_spec(wrong)


def test_eleventh_cannot_be_relabelled_to628_or_model_hash():
    wrong=deepcopy(spec());wrong['repairs'][10]['resume_session']='2020-06-30'
    with pytest.raises(ValueError):parent.check_spec(wrong)
    wrong=deepcopy(spec());wrong['repairs'][10]['sha256']='fd4eacb7f847f82e2147e70e0206b4df358c7f38ad09026e4afe23153c1410db'
    with pytest.raises(ValueError):parent.check_spec(wrong)
    wrong=deepcopy(spec());wrong['retained_checkpoint_files'].pop('lineage/0.json.gz')
    with pytest.raises(ValueError):parent.check_spec(wrong)


@pytest.mark.parametrize('field',['reporting_precision','roles','nav','raw_open','local_path'])
def test_public_parent_spec_rejects_unlisted_private_fields(field):
    wrong=spec();wrong[field]='forbidden'
    with pytest.raises(ValueError):parent.check_spec(wrong)


def test_source_epoch_public_descriptors_have_no_private_paths():
    wrong=spec();wrong['source_epoch']['successor_source_map']['path']='private-local-path'
    with pytest.raises(ValueError):parent.check_spec(wrong)


@pytest.mark.parametrize('guard_name,private_kind',[
    ('PUBLIC_SPEC_EXPLICIT_METADATA_ALLOWLIST','outer'),('PUBLIC_SOURCE_EPOCH_NO_LOCAL_PATHS','epoch')])
def test_new_public_metadata_guards_have_removal_falsifiers(guard_name,private_kind):
    wrong=spec()
    if private_kind=='outer':wrong['roles']='forbidden'
    else:wrong['source_epoch']['successor_source_map']['path']='forbidden'
    with pytest.raises(ValueError):parent.check_spec(wrong)
    tree=ast.parse(textwrap.dedent(inspect.getsource(parent.check_spec)))
    guard=next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value==guard_name for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(parent))
    exec(compile(ast.fix_missing_locations(tree),'<public-parent-metadata-guard-removal>','exec'),ns)
    assert ns['check_spec'](wrong)==wrong


def test_actual_synthetic_gcm_scope_and_inventory(tmp_path):
    archive,asset=capsule(tmp_path)
    with zipfile.ZipFile(archive) as z:members=parent._extract(z,asset,b'k'*32,tmp_path/'out',parent.STAGE)
    assert set(members)=={'proof.txt'} and (tmp_path/'out/proof.txt').read_bytes()==b'synthetic nonfinancial proof only'


def test_wrong_gcm_refuses_before_directory_or_private_manifest(tmp_path):
    archive,asset=capsule(tmp_path)
    with zipfile.ZipFile(archive) as z,pytest.raises(InvalidTag):parent._extract(z,asset,b'x'*32,tmp_path/'out',parent.STAGE)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('kwargs',[dict(protocol='0'*64),dict(stage='WRONG'),dict(extra=True),dict(bad_member=True)])
def test_wrong_scope_or_incomplete_inventory_refuses(tmp_path,kwargs):
    archive,asset=capsule(tmp_path,**kwargs)
    with zipfile.ZipFile(archive) as z,pytest.raises(ValueError):parent._extract(z,asset,b'k'*32,tmp_path/'out',parent.STAGE)


def test_authentication_guard_removal_falsifier(tmp_path,monkeypatch):
    import system_campaign_factual_admit as crypto
    archive,asset=capsule(tmp_path)
    with zipfile.ZipFile(archive) as z:raw=z.read(asset['name'])
    monkeypatch.setattr(crypto,'authenticate',lambda *args:(raw[:20],raw[-16:]))
    with zipfile.ZipFile(archive) as z,pytest.raises((tarfile.ReadError,InvalidTag)):
        parent._extract(z,asset,b'x'*32,tmp_path/'out',parent.STAGE)
    assert (tmp_path/'out').exists()


def actual_capture():
    path=os.environ.get('P01_IAC628_PRIVATE_CAPTURE')
    if not path:pytest.skip('immutable private capture is absent from public Git')
    p=Path(path)
    if os.name=='nt' and not str(p).startswith('\\\\?\\'):p=Path('\\\\?\\'+str(p.resolve()))
    return p


def test_actual_cached628_metadata_and_all38_files_without_financial_decode():
    p=actual_capture();raw=(p.parent/'admitted-financial-predecessor-628.json').read_bytes()
    assert parent.sha(raw)==parent.ROOT_ADMISSION
    value=json.loads((p.parent.parent/'iac-unit-001/safe-own628-predecessor-skeleton-001.json').read_bytes())
    manifest=json.loads((p/'financial-authenticated-manifest.json').read_bytes())
    value['retained_checkpoint_files']={n:v for n,v in manifest['members'].items()
        if n.startswith(('book/','lineage/')) and n.endswith('.json.gz')}
    cp=parent.validate_contents(p/'verified-financial',value)
    assert cp['completed']==628 and len(cp['repairs'])==11
    assert not any(n.startswith(('sentinel','stock_strategy_shared','research.pooled_')) for n in sys.modules)


def test_actual_cached468_receipt_marker_and_three_stop_adapter():
    p=actual_capture()
    with zipfile.ZipFile(p/'artifact.zip') as z:
        raw=z.read('p01-native-resume.json');assert parent.sha(raw)==parent.RECEIPT
        assert parent.sha(z.read('p01-native-resume-export-qualification.json'))==parent.MARKER
        receipt=json.loads(raw)
    source=(parent.HERE/'system_campaign_p02_close_diagnostics.py').read_bytes()
    for role,name,field in [('qualify','qualification/worker-inspect.json','qualification_worker'),
        ('worker','worker-inspect.json','worker'),('review','stopped-review/worker-inspect.json','reviewer')]:
        value=json.loads((p/'verified-financial'/name).read_bytes());parent.stopped(value,receipt[field],role,source)
