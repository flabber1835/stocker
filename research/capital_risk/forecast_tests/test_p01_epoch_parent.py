"""Metadata and real synthetic AES-GCM only; no financial runtime imports."""
from copy import deepcopy
import gzip
import io
import json
import os
from pathlib import Path
import sys
import tarfile
from typing import get_args
import zipfile

from cryptography.exceptions import InvalidTag
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import p01_epoch_parent as parent
import seal


def spec():
    value = {n:get_args(f.annotation)[0] for n,f in parent.IdentityPins.model_fields.items()}
    value.update(selected_file=parent.GZIP, selected_checkpoint='book/checkpoint.json.gz',
        request_sha256=parent.PRIOR_SHA, repairs=[dict(sha256='0'*64)]*9+[dict(sha256=parent.TENTH)],
        protocol_sha256=parent.PROTOCOL,stage=parent.STAGE,next_session='2020-02-05',
        source_epoch=dict(original_physical=515,successor_physical=516,original_canonical=223,successor_canonical=224,
            original_source_bindings=dict(sha256=parent.OLD_BINDING),successor_source_map=dict(sha256=parent.SOURCE_MAP),
            successor_source_map_identity_sha256=parent.MAP_IDENTITY))
    return value


def capsule(tmp_path, *, protocol=parent.PROTOCOL, stage=parent.STAGE, extra=False, bad_member=False):
    payload = b'nonfinancial synthetic inventory test'
    manifest = dict(schema='research.full-system-output/1', stage=stage, arm='P01', run_id=str(parent.RUN),
        head=parent.HEAD, request_sha256=parent.PRIOR_SHA, protocol_sha256=protocol,
        members={'proof.txt':dict(bytes=len(payload), sha256='0'*64 if bad_member else parent.sha(payload))})
    raw = json.dumps(manifest, sort_keys=True).encode(); plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode='w:gz') as tar:
        for name, body in [('manifest.json',raw),('proof.txt',payload)]+([('extra.txt',b'x')] if extra else []):
            entry=tarfile.TarInfo(name);entry.size=len(body);tar.addfile(entry,io.BytesIO(body))
    encrypted=io.BytesIO();writer=seal.EncryptWriter(encrypted,b'k'*32);writer.write(plain.getvalue());writer.finish()
    cipher=encrypted.getvalue();path=tmp_path/'fixture.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('synthetic.crseal',cipher)
    return path,dict(name='synthetic.crseal',bytes=len(cipher),sha256=parent.sha(cipher),manifest_sha256=parent.sha(raw))


def test_exact_metadata_projection():
    assert parent.check_spec(spec())['measured_closes']==526


@pytest.mark.parametrize('field,value', [('root_admission_descriptor_sha256','0'*64),
    ('outer_sha256','0'*64),('qualification_state_adopted',True),('financial_predecessor_admitted',1),
    ('current_tails_zero',1),('selected_session','2019-11-19'),('protocol_sha256','0'*64),
    ('next_session','2020-02-06')])
def test_wrong_admission_refuses(field,value):
    wrong=deepcopy(spec());wrong[field]=value
    with pytest.raises(ValueError):parent.check_spec(wrong)


def test_actual_aes_gcm_inventory_wrapper(tmp_path):
    archive,asset=capsule(tmp_path)
    with zipfile.ZipFile(archive) as z:
        inventory=parent._extract(z,asset,b'k'*32,tmp_path/'out',parent.STAGE)
    assert (tmp_path/'out/proof.txt').read_bytes()==b'nonfinancial synthetic inventory test'
    assert set(inventory)=={'proof.txt'}


def test_wrong_gcm_before_any_private_parse_or_destination(tmp_path):
    archive,asset=capsule(tmp_path)
    with zipfile.ZipFile(archive) as z,pytest.raises(InvalidTag):
        parent._extract(z,asset,b'x'*32,tmp_path/'out',parent.STAGE)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('kwargs', [dict(protocol='0'*64),dict(stage='OTHER'),dict(extra=True),dict(bad_member=True)])
def test_complete_scope_inventory_guards(tmp_path,kwargs):
    archive,asset=capsule(tmp_path,**kwargs)
    with zipfile.ZipFile(archive) as z,pytest.raises(ValueError):
        parent._extract(z,asset,b'k'*32,tmp_path/'out',parent.STAGE)


def test_authentication_guard_removal_falsifier(tmp_path,monkeypatch):
    import system_campaign_factual_admit as crypto
    archive,asset=capsule(tmp_path)
    with zipfile.ZipFile(archive) as z:raw=z.read(asset['name'])
    # Removing authenticate publishes an extraction directory before invalid
    # plaintext/GCM is rejected. The normal test above forbids that outcome.
    monkeypatch.setattr(crypto,'authenticate',lambda *args:(raw[:20],raw[-16:]))
    with zipfile.ZipFile(archive) as z,pytest.raises((tarfile.ReadError,InvalidTag)):
        parent._extract(z,asset,b'x'*32,tmp_path/'out',parent.STAGE)
    assert (tmp_path/'out').exists()


def test_actual_admitted_metadata_no_financial_decode():
    directory=os.environ.get('P01_EPOCH_PRIVATE_CAPTURE')
    if not directory:pytest.skip('private immutable capture is deliberately absent from public Git')
    root=Path(directory)
    if os.name=='nt' and not str(root).startswith('\\\\?\\'):
        root=Path('\\\\?\\'+str(root.resolve()))
    raw=(root.parent/'admitted-financial-predecessor-526.json').read_bytes()
    assert parent.sha(raw)==parent.ROOT_ADMISSION
    value=json.loads(raw);value['root_admission_descriptor_sha256']=parent.ROOT_ADMISSION
    cp=parent.validate_contents(root/'verified-financial',value)
    assert cp['completed']==526 and len(cp['repairs'])==10
    assert not any(n.startswith(('sentinel','stock_strategy_shared','research.pooled_')) for n in sys.modules)


def test_actual_cached_public_and_stop_adapter():
    directory=os.environ.get('P01_EPOCH_PRIVATE_CAPTURE')
    if not directory:pytest.skip('private immutable capture is deliberately absent from public Git')
    root=Path(directory)
    if os.name=='nt' and not str(root).startswith('\\\\?\\'):root=Path('\\\\?\\'+str(root.resolve()))
    with zipfile.ZipFile(root/'artifact.zip') as z:
        raw=z.read('p01-celg-bridge.json')
        assert parent.sha(raw)==parent.RECEIPT
        receipt=json.loads(raw)
        assert parent.sha(z.read('p01-celg-bridge-export-qualification.json'))==parent.MARKER
    source=(parent.HERE/'system_campaign_p02_close_diagnostics.py').read_bytes()
    for role,name,field in [('qualify','qualification/worker-inspect.json','qualification_worker'),
                            ('worker','worker-inspect.json','worker'),('review','stopped-review/worker-inspect.json','reviewer')]:
        value=json.loads((root/'verified-financial'/name).read_bytes())
        parent.stopped(value,receipt[field],role,source)
