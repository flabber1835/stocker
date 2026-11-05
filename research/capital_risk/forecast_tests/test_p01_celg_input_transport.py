"""Pure transport tests; private retained fixtures are never public test payloads."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal
import gzip
import io
import json
import os
from pathlib import Path
import sys
import tarfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import p01_celg_input_transport as transport


@pytest.fixture
def private_sources():
    root=Path(os.environ.get('P01_CELG_PRIVATE_INPUT_DIRECTORY',str(HERE)))
    quote=root/'p01_celg_multileg_quote.json.gz';capture=root/'p01_celg_multileg_quote_capture.json'
    if not quote.exists() or not capture.exists():
        pytest.skip('retained private capture is deliberately absent from public Git')
    return quote,capture


@pytest.fixture
def prepared(tmp_path,private_sources):
    key=os.urandom(32);quote,capture=private_sources
    root=tmp_path/'capsule'
    descriptor=transport.prepare_capsule(quote,capture,root,key=key)
    return root,key,descriptor


def download_stub(monkeypatch,source):
    def acquire(name,spec,root):
        raw=(source/name).read_bytes()
        assert spec==dict(bytes=len(raw),sha256=transport.sha(raw))
        path=root/name;path.write_bytes(raw)
        return path
    monkeypatch.setattr(transport.alpaca_fit_stage,'acquire',acquire)


def repackage(tmp_path,key,descriptor,members,manifest=None):
    raw=io.BytesIO()
    manifest=deepcopy(manifest) if manifest is not None else dict(schema='research.p01-celg-captured-inputs/1',
        authority='CAPTURED_MARKET_INPUT_ONLY_NOT_FINANCIAL_ADMISSION',
        provenance=transport.provenance(),members=transport.MEMBERS)
    manifest_raw=transport.encoded(manifest)
    with tarfile.open(fileobj=raw,mode='w') as archive:
        entries=[('manifest.json',manifest_raw)]+members
        for name,payload in entries:
            item=tarfile.TarInfo(name);item.size=len(payload)
            archive.addfile(item,io.BytesIO(payload))
    header=transport.seal.MAGIC+os.urandom(12)
    cipher=header+AESGCM(key).encrypt(header[8:],raw.getvalue(),header)
    result=deepcopy(descriptor);result['manifest_sha256']=transport.sha(manifest_raw)
    result['ciphertext_sha256']=transport.sha(cipher);result['ciphertext_bytes']=len(cipher)
    result['asset_name']='p01-celg-input-'+result['ciphertext_sha256']+'.tar.crseal'
    result['asset_url']=f'https://github.com/{transport.REPOSITORY}/releases/download/{transport.RELEASE}/'+result['asset_name']
    root=tmp_path/'repacked';root.mkdir();(root/result['asset_name']).write_bytes(cipher)
    return root,result


def test_exact_actual_capture_packages_and_authenticates_without_network(prepared,private_sources,tmp_path,monkeypatch):
    root,key,descriptor=prepared;download_stub(monkeypatch,root)
    value=transport.authenticate_capsule(descriptor,tmp_path/'hosted',key=key)
    repeated=transport.load_authenticated_input(tmp_path/'hosted',descriptor)
    assert value==repeated
    assert value.authority==transport.AUTHORITY and value.financial_input_admitted is False
    quote,capture=private_sources
    actual=transport.parse(gzip.decompress(quote.read_bytes()))['bars']['BMY.RT'][0]
    assert Decimal(value.quote.raw_open)==actual['o'] and Decimal(value.quote.raw_close)==actual['c']
    assert value.quote.model_dump(mode='json')['identity']['provider_symbol']=='BMY.RT'
    assert value.quote_gzip_sha256==transport.QUOTE_GZIP_SHA and value.capture_sha256==transport.CAPTURE_SHA
    with pytest.raises(FrozenInstanceError):value.authority='SYNTHETIC'
    with pytest.raises(ValueError):value.quote.raw_open='1'
    assert descriptor['provenance']['crypto_transport_protocol_sha256']==transport.CRYPTO_PROTOCOL
    assert descriptor['provenance']['consumer_financial_protocol_sha256']==transport.CONSUMER_PROTOCOL
    assert transport.CRYPTO_PROTOCOL!=transport.CONSUMER_PROTOCOL


def test_original_random_nonce_full_header_aad_and_tag_are_actually_used(prepared):
    root,key,descriptor=prepared
    raw=(root/descriptor['asset_name']).read_bytes();header=raw[:20]
    assert header[:8]==b'CRSEAL01' and len(header[8:])==12 and len(raw[-16:])==16
    plain=AESGCM(key).decrypt(header[8:],raw[20:],header)
    assert (root/'local-authentication/capsule.tar').read_bytes()==plain
    with pytest.raises(InvalidTag):AESGCM(key).decrypt(header[8:],raw[20:],b'')
    with pytest.raises(InvalidTag):AESGCM(key).decrypt(bytes(12),raw[20:],header)


def test_bad_gcm_refuses_before_any_manifest_or_private_payload_parser(prepared,tmp_path,monkeypatch):
    root,key,descriptor=prepared;download_stub(monkeypatch,root)
    monkeypatch.setattr(transport,'unpack_authenticated',lambda *args:pytest.fail('parsed before GCM'))
    with pytest.raises(InvalidTag):
        transport.authenticate_capsule(descriptor,tmp_path/'wrong-key',key=os.urandom(32))
    assert not (tmp_path/'wrong-key/manifest.json').exists()
    assert not (tmp_path/'wrong-key/capsule.tar').exists()


@pytest.mark.parametrize('change',['manifest','unit','provider','asof','extra_manifest'])
def test_authenticated_wrong_manifest_or_provenance_refuses(prepared,private_sources,tmp_path,monkeypatch,change):
    _,key,descriptor=prepared;quote,capture=private_sources
    manifest=dict(schema='research.p01-celg-captured-inputs/1',
        authority='CAPTURED_MARKET_INPUT_ONLY_NOT_FINANCIAL_ADMISSION',
        provenance=transport.provenance(),members=deepcopy(transport.MEMBERS))
    if change=='manifest':manifest['members']['quote.json.gz']['sha256']='0'*64
    elif change=='extra_manifest':manifest['extra_private_field']=True
    else:manifest['provenance'][{'unit':'quote_unit','asof':'asof','provider':'provider'}[change]]='WRONG'
    source,changed=repackage(tmp_path,key,descriptor,[('quote.json.gz',quote.read_bytes()),('capture.json',capture.read_bytes())],manifest)
    download_stub(monkeypatch,source)
    with pytest.raises(ValueError):transport.authenticate_capsule(changed,tmp_path/'rejected',key=key)
    assert not (tmp_path/'rejected/quote.json.gz').exists()


@pytest.mark.parametrize('case',['extra','duplicate','wrong_preimage','path'])
def test_complete_inventory_and_every_preimage_precede_decoding(prepared,private_sources,tmp_path,monkeypatch,case):
    _,key,descriptor=prepared;quote,capture=private_sources
    members=[('quote.json.gz',quote.read_bytes()),('capture.json',capture.read_bytes())]
    if case=='extra':members.append(('extra.json',b'{}'))
    elif case=='duplicate':members.append(members[0])
    elif case=='path':members[0]=('../quote.json.gz',members[0][1])
    else:members[0]=('quote.json.gz',b'CHANGED')
    source,changed=repackage(tmp_path,key,descriptor,members);download_stub(monkeypatch,source)
    monkeypatch.setattr(transport,'decode_payloads',lambda *args:pytest.fail('decoded before full inventory'))
    with pytest.raises(ValueError):transport.authenticate_capsule(changed,tmp_path/'rejected',key=key)


@pytest.mark.parametrize('key,value',[('quote_unit','ORDINARY_SHARE'),('asof','2019-11-20'),
    ('provider','OTHER'),('consumer_financial_protocol_sha256',transport.CRYPTO_PROTOCOL),
    ('crypto_transport_protocol_sha256',transport.CONSUMER_PROTOCOL)])
def test_public_unit_asof_provider_and_both_protocol_namespaces_are_strict(key,value):
    raw=transport.provenance();raw[key]=value
    with pytest.raises(ValueError):transport.Provenance.model_validate(raw)


def test_duplicate_nonfinite_and_credential_keys_refuse():
    with pytest.raises(ValueError,match='DUPLICATE'):transport.parse(b'{"a":1,"a":2}')
    with pytest.raises(ValueError,match='NONFINITE'):transport.parse(b'{"a":NaN}')
    with pytest.raises(ValueError,match='CREDENTIAL'):transport.reject_credentials({'nested':{'Authorization':'PRIVATE'}})
    value=transport.provenance();value['extra']=False
    with pytest.raises(ValueError):transport.Provenance.model_validate(value)


def test_capture_query_guards_and_all_extra_fields_reject(private_sources):
    _,capture=private_sources;value=transport.parse(capture.read_bytes())
    for key,new in [('endpoint','https://broker.invalid/account'),('params',dict(value['receipts'][1]['params'],asof='2019-11-20'))]:
        bad=deepcopy(value);bad['receipts'][1][key]=new
        with pytest.raises(ValueError,match='PROVIDER_RAW_SIP_ASOF'):transport.validate_capture(bad)
    value['receipts'][1]['headers']={}
    with pytest.raises(ValueError):transport.validate_capture(value)


def test_mutated_retained_files_and_authentication_proof_cannot_be_reloaded(prepared):
    root,_,descriptor=prepared;admitted=root/'local-authentication'
    proof=admitted/'authentication.json';value=transport.parse(proof.read_bytes());value['actual_gcm_authenticated_before_parsing']=False
    proof.write_bytes(transport.encoded(value))
    with pytest.raises(ValueError,match='AUTHENTICATION_RECEIPT'):transport.load_authenticated_input(admitted,descriptor)


def test_member_preimage_guard_removal_falsifier(prepared,private_sources,tmp_path,monkeypatch):
    _,key,descriptor=prepared;quote,capture=private_sources
    source,changed=repackage(tmp_path,key,descriptor,[('quote.json.gz',b'CHANGED'),('capture.json',capture.read_bytes())])
    root=tmp_path/'mutant';root.mkdir();(root/changed['asset_name']).write_bytes((source/changed['asset_name']).read_bytes())
    transport.seal.decrypt(root/changed['asset_name'],root/'capsule.tar',key,changed['ciphertext_sha256'])
    tree=ast.parse(Path(transport.__file__).read_bytes())
    fn,=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='unpack_authenticated']
    class Remove(ast.NodeTransformer):
        removed=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and ast.unparse(node.value.func)=='need' and len(node.value.args)==2 \
                and isinstance(node.value.args[1],ast.Constant) and node.value.args[1].value=='ALL_MEMBER_PREIMAGES_BEFORE_ANY_PAYLOAD_PARSE':
                self.removed+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=remove.visit(fn);assert remove.removed==1
    reached=[];scope=dict(vars(transport),decode_payloads=lambda *args:reached.append(args) or None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<transport-guard-removal>','exec'),scope)
    scope['unpack_authenticated'](root,transport.validate_descriptor(changed))
    assert reached and reached[0][0]==b'CHANGED'


def test_new_capsule_never_overwrites_a_prior_destination(prepared,private_sources):
    root,key,_=prepared;quote,capture=private_sources
    before={path.name for path in root.iterdir()}
    with pytest.raises(ValueError,match='FRESH_DISJOINT'):
        transport.prepare_capsule(quote,capture,root,key=key)
    assert {path.name for path in root.iterdir()}==before


def test_trailing_archive_payload_is_not_hidden_by_tar_end_markers(prepared,tmp_path,monkeypatch):
    root,key,descriptor=prepared
    plain=(root/'local-authentication/capsule.tar').read_bytes()+b'UNDECLARED_PAYLOAD'
    header=transport.seal.MAGIC+os.urandom(12);cipher=header+AESGCM(key).encrypt(header[8:],plain,header)
    changed=deepcopy(descriptor);changed['ciphertext_sha256']=transport.sha(cipher)
    changed['ciphertext_bytes']=len(cipher);changed['asset_name']='p01-celg-input-'+changed['ciphertext_sha256']+'.tar.crseal'
    changed['asset_url']=f'https://github.com/{transport.REPOSITORY}/releases/download/{transport.RELEASE}/'+changed['asset_name']
    source=tmp_path/'trailing';source.mkdir();(source/changed['asset_name']).write_bytes(cipher)
    download_stub(monkeypatch,source)
    with pytest.raises(ValueError,match='TRAILING_ARCHIVE_PAYLOAD'):
        transport.authenticate_capsule(changed,tmp_path/'reject-trailing',key=key)


def test_existing_cipher_recovery_preserves_exact_bytes_nonce_and_failed_source(prepared,private_sources,tmp_path,monkeypatch):
    root,key,descriptor=prepared;quote,capture=private_sources;source=root/descriptor['asset_name']
    raw=source.read_bytes()
    monkeypatch.setattr(transport.local_stage,'pack_data',lambda *args:pytest.fail('existing cipher was resealed'))
    changed=transport.prepare_capsule(quote,capture,tmp_path/'recovered',key=key,existing_cipher=source)
    assert changed==descriptor and source.read_bytes()==raw
    assert (tmp_path/'recovered'/descriptor['asset_name']).read_bytes()==raw


def test_deep_private_windows_path_and_content_addressed_filename(private_sources,tmp_path):
    quote,capture=private_sources
    root=tmp_path
    for index in range(20):root=root/('private-capsule-scope-'+str(index))
    descriptor=transport.prepare_capsule(quote,capture,root,key=os.urandom(32))
    assert transport.private_path(root/descriptor['asset_name']).is_file()
    if os.name=='nt':assert str(transport.private_path(root)).startswith(chr(92)*2+'?'+chr(92))


def test_native_path_normalization_does_not_hide_a_symlink(private_sources,tmp_path):
    quote,_=private_sources;link=tmp_path/'quote-link.gz'
    try:link.symlink_to(quote)
    except OSError:pytest.skip('host does not grant symlink creation')
    with pytest.raises(ValueError,match='BOUNDED_REGULAR_INPUT_FILE'):
        transport.read_bounded(link,263)


def test_fresh_preparations_have_distinct_nonces_and_cipher_addresses(private_sources,tmp_path):
    quote,capture=private_sources;key=os.urandom(32)
    first=transport.prepare_capsule(quote,capture,tmp_path/'first',key=key)
    second=transport.prepare_capsule(quote,capture,tmp_path/'second',key=key)
    assert first['manifest_sha256']==second['manifest_sha256']
    assert first['ciphertext_sha256']!=second['ciphertext_sha256']
    assert (tmp_path/'first'/first['asset_name']).read_bytes()[8:20]!=(tmp_path/'second'/second['asset_name']).read_bytes()[8:20]


@pytest.mark.parametrize('field',['financial_input_admitted','financial_state_included','provider_credentials_included'])
def test_numeric_false_cannot_relabel_public_authority_flags(field):
    value=transport.provenance();value[field]=0
    with pytest.raises(ValueError,match='FALSE_PROVENANCE_FLAGS'):
        transport.Provenance.model_validate(value)
