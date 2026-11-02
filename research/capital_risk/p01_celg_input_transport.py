"""Private captured quote transport only. No upload, provider or financial runtime."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import alpaca_fit_stage
import local_stage
import seal

REPOSITORY = 'flabber1835/stocker'
RELEASE = 'research-capital-risk-inputs-20261027'
CRYPTO_PROTOCOL = 'a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52'
CONSUMER_PROTOCOL = 'a5bacaa1bc51bb5ac376b5163186208aeb4d3aedd130fa7ccdb5e54058cb26d3'
QUOTE_GZIP_SHA = '17358d350e627caa2eda430fbad850a4f13e68f6db689428bcb270ae876aa455'
QUOTE_RAW_SHA = 'fbbd4ee52eadf5e8498c2ab3135b9b368b35a5f9354941a06307468b96e24769'
CAPTURE_SHA = 'fdd7ed3e8d918d02b8fe927b0063cd1737205cfad1fc006a7e8000b2515a3a06'
SEAL_SHA = '9671e34e6895e594d20e6e1800c4899092c2da32ac33af7fecc93e26371bcc95'
PACK_SHA = 'cad185d6a5e65c928a45afd93d1aab2b0e5bcff261c3b63a11c576bd9b611350'
ACQUIRE_SHA = '8339b44a2d3ed9bef5004d97f7ffd75ebad934697bcf7d085f2ffb9e4986023c'
AUTHORITY = 'AUTHENTICATED_CAPTURED_MARKET_INPUT_ONLY'
CAPSULE_MAX = 64 * 1024
EXPANDED_MAX = 16 * 1024
DESCRIPTOR = 'p01-celg-input-descriptor-001.json'
PUBLIC_KEYS = {'schema','repository','release','asset_name','asset_url','ciphertext_bytes',
               'ciphertext_sha256','manifest_sha256','provenance'}
MEMBERS = {'quote.json.gz':dict(bytes=263,sha256=QUOTE_GZIP_SHA),
           'capture.json':dict(bytes=2197,sha256=CAPTURE_SHA)}
Sha = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


def need(value, code):
    if not value:
        raise ValueError('P01_CELG_TRANSPORT_'+code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def digest(value):
    return sha(encoded(value))


def private_path(value):
    path=Path(os.path.abspath(value))
    prefix=chr(92)*2+'?'+chr(92)
    return Path(prefix+str(path)) if os.name=='nt' and not str(path).startswith(prefix) else path


def parse(raw):
    need(type(raw) is bytes and len(raw)<=EXPANDED_MAX,'JSON_BOUND')
    def pairs(items):
        value={}
        for key,item in items:
            need(key not in value,'DUPLICATE_JSON_KEY')
            value[key]=item
        return value
    def invalid(_):
        raise ValueError('P01_CELG_TRANSPORT_NONFINITE_JSON')
    return json.loads(raw,object_pairs_hook=pairs,parse_float=Decimal,parse_constant=invalid)


class Frozen(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,frozen=True)


class Commitment(Frozen):
    bytes: Annotated[int, Field(ge=0,le=EXPANDED_MAX)]
    sha256: Sha


class Provenance(Frozen):
    crypto_transport_protocol_sha256: Literal[CRYPTO_PROTOCOL]
    consumer_financial_protocol_sha256: Literal[CONSUMER_PROTOCOL]
    provider: Literal['ALPACA_MARKET_DATA']
    endpoint: Literal['https://data.alpaca.markets/v2/stocks/bars']
    provider_symbol: Literal['BMY.RT']
    legal_symbol: Literal['BMYRT']
    quote_unit: Literal['ONE_LISTED_CONTINGENT_VALUE_RIGHT']
    asof: Literal['2019-11-21']
    adjustment: Literal['raw']
    feed: Literal['sip']
    gzip: Commitment
    raw_response: Commitment
    capture: Commitment
    seal_source_sha256: Literal[SEAL_SHA]
    pack_source_sha256: Literal[PACK_SHA]
    acquire_source_sha256: Literal[ACQUIRE_SHA]
    financial_input_admitted: Literal[False]
    financial_state_included: Literal[False]
    provider_credentials_included: Literal[False]

    @model_validator(mode='before')
    @classmethod
    def exact_false_flags(cls,value):
        need(type(value) is dict and all(value.get(name) is False for name in
             ('financial_input_admitted','financial_state_included','provider_credentials_included')),
             'EXACT_FALSE_PROVENANCE_FLAGS_NOT_NUMERIC_COERCIONS')
        return value

    @model_validator(mode='after')
    def exact_preimages(self):
        need(self.gzip.model_dump()==MEMBERS['quote.json.gz']
             and self.capture.model_dump()==MEMBERS['capture.json']
             and self.raw_response.model_dump()==dict(bytes=473,sha256=QUOTE_RAW_SHA),
             'EXACT_CAPTURED_SOURCE_COMMITMENTS')
        return self


class CapsuleManifest(Frozen):
    schema_id: Literal['research.p01-celg-captured-inputs/1'] = Field(alias='schema')
    authority: Literal['CAPTURED_MARKET_INPUT_ONLY_NOT_FINANCIAL_ADMISSION']
    provenance: Provenance
    members: dict[str,Commitment]

    @model_validator(mode='after')
    def exact_members(self):
        need({name:item.model_dump() for name,item in self.members.items()}==MEMBERS,
             'EXACT_TWO_CAPTURED_INPUT_MEMBERS')
        return self


class PublicDescriptor(Frozen):
    schema_id: Literal['research.p01-celg-input-capsule/1'] = Field(alias='schema')
    repository: Literal[REPOSITORY]
    release: Literal[RELEASE]
    asset_name: str
    asset_url: str
    ciphertext_bytes: Annotated[int, Field(gt=36,le=CAPSULE_MAX)]
    ciphertext_sha256: Sha
    manifest_sha256: Sha
    provenance: Provenance

    @model_validator(mode='after')
    def exact_route(self):
        need(self.asset_name=='p01-celg-input-'+self.ciphertext_sha256+'.tar.crseal'
             and self.asset_url==f'https://github.com/{REPOSITORY}/releases/download/{RELEASE}/'+self.asset_name,
             'EXACT_CONTENT_ADDRESSED_EXISTING_RELEASE_ROUTE')
        return self


class Identity(Frozen):
    issuer_cik: Literal['14272'] = '14272'
    legal_symbol: Literal['BMYRT'] = 'BMYRT'
    provider_symbol: Literal['BMY.RT'] = 'BMY.RT'
    legal_source_accession: Literal['0001104659-19-065939'] = '0001104659-19-065939'
    legal_source_url: Literal['https://www.sec.gov/Archives/edgar/data/816284/000110465919065939/tm1923405d1_8k.htm'] = \
        'https://www.sec.gov/Archives/edgar/data/816284/000110465919065939/tm1923405d1_8k.htm'
    canonical_security_id: None = None
    alpha_eligible: Literal[False] = False


class Quote(Frozen):
    identity: Identity
    session: Literal['2019-11-21'] = '2019-11-21'
    source_timestamp: Literal['2019-11-21T05:00:00Z'] = '2019-11-21T05:00:00Z'
    raw_open: str
    raw_close: str
    adjustment: Literal['raw'] = 'raw'
    feed: Literal['sip'] = 'sip'
    gzip_sha256: Literal[QUOTE_GZIP_SHA] = QUOTE_GZIP_SHA
    raw_sha256: Literal[QUOTE_RAW_SHA] = QUOTE_RAW_SHA

    @field_validator('raw_open','raw_close')
    @classmethod
    def positive_exact_decimal(cls,value):
        number=Decimal(value)
        need(number.is_finite() and number>0,'POSITIVE_EXACT_CAPTURED_QUOTE')
        return value


@dataclass(frozen=True)
class AuthenticatedCelgInput:
    quote: Quote
    quote_gzip_sha256: str
    quote_raw_sha256: str
    capture_sha256: str
    manifest_sha256: str
    ciphertext_sha256: str
    input_identity_sha256: str
    authority: str = field(default=AUTHORITY,init=False)
    financial_input_admitted: bool = field(default=False,init=False)


def provenance():
    return dict(crypto_transport_protocol_sha256=CRYPTO_PROTOCOL,
        consumer_financial_protocol_sha256=CONSUMER_PROTOCOL,provider='ALPACA_MARKET_DATA',
        endpoint='https://data.alpaca.markets/v2/stocks/bars',provider_symbol='BMY.RT',legal_symbol='BMYRT',
        quote_unit='ONE_LISTED_CONTINGENT_VALUE_RIGHT',asof='2019-11-21',adjustment='raw',feed='sip',
        gzip=MEMBERS['quote.json.gz'],raw_response=dict(bytes=473,sha256=QUOTE_RAW_SHA),
        capture=MEMBERS['capture.json'],seal_source_sha256=SEAL_SHA,pack_source_sha256=PACK_SHA,
        acquire_source_sha256=ACQUIRE_SHA,financial_input_admitted=False,
        financial_state_included=False,provider_credentials_included=False)


def exact_crypto_sources():
    need(seal.sha256_file(Path(seal.__file__))==SEAL_SHA
         and seal.sha256_file(Path(local_stage.__file__))==PACK_SHA
         and seal.sha256_file(Path(alpaca_fit_stage.__file__))==ACQUIRE_SHA
         and local_stage.EncryptWriter is seal.EncryptWriter
         and seal.MAGIC==b'CRSEAL01','ORIGINAL_CRYPTO_AND_ACQUIRE_IMPLEMENTATIONS')


def reject_credentials(value):
    forbidden={'authorization','headers','api_key','api_secret','apca_api_key_id',
               'apca_api_secret_key','cookie','cookies','access_token','secret'}
    if isinstance(value,dict):
        need(not {key.lower().replace('-','_') for key in value}.intersection(forbidden),
             'NO_CREDENTIAL_OR_HEADER_PAYLOAD')
        for child in value.values():reject_credentials(child)
    elif isinstance(value,list):
        for child in value:reject_credentials(child)


def validate_capture(value):
    reject_credentials(value)
    need(set(value)=={'schema','PAPER_mutated','bar_counts','broker_or_account_endpoints_called',
         'no_local_financial_execution','receipts','terms_admitted'}
         and value['schema']=='research.alpaca-cvr-market-only-probe/1'
         and value['PAPER_mutated'] is False and value['broker_or_account_endpoints_called'] is False
         and value['no_local_financial_execution'] is True and value['terms_admitted'] is False
         and value['bar_counts']=={'BMY':2,'BMY.RT':2}
         and type(value['receipts']) is list and len(value['receipts'])==3,'EXACT_MARKET_ONLY_CAPTURE_SCHEMA')
    query=dict(adjustment='raw',asof='2019-11-21',end='2019-11-23T00:00:00Z',feed='sip',limit=100,
               sort='asc',start='2019-11-21T00:00:00Z',timeframe='1Day')
    for index,item in enumerate(value['receipts']):
        keys={'endpoint','observed_utc','params','status'}
        keys|={'bytes','file','raw_bytes','raw_sha256','sha256'} if index<2 else {'http_status'}
        need(set(item)==keys and item['endpoint']=='https://data.alpaca.markets/v2/stocks/bars'
             and item['params']==dict(query,symbols=('BMY,BMYRT','BMY,BMY.RT','BMY,BMY/RT')[index]),
             'EXACT_PROVIDER_RAW_SIP_ASOF_QUERY')
        need(datetime.fromisoformat(item['observed_utc']).utcoffset().total_seconds()==0,
             'UTC_CAPTURE_RECEIPT_TIMESTAMP')
        if index<2:
            need(item['status']=='RESPONSE_CAPTURED' and item['file']==f'provider-{index:03d}.json.gz'
                 and type(item['bytes']) is int and type(item['raw_bytes']) is int
                 and re.fullmatch('[0-9a-f]{64}',item['sha256'])
                 and re.fullmatch('[0-9a-f]{64}',item['raw_sha256']),'EXACT_CAPTURED_RECEIPT_SHAPE')
        else:
            need(item['status']=='HTTP_REFUSAL' and type(item['http_status']) is int
                 and item['http_status']==400,'PRESERVED_ALTERNATE_SYMBOL_REFUSAL')
    chosen=value['receipts'][1]
    need(chosen['bytes']==263 and chosen['raw_bytes']==473 and chosen['sha256']==QUOTE_GZIP_SHA
         and chosen['raw_sha256']==QUOTE_RAW_SHA,'EXACT_SELECTED_CAPTURE_RECEIPT_PREIMAGES')


def decode_payloads(compressed,capture_raw):
    need(type(compressed) is bytes and len(compressed)==263 and sha(compressed)==QUOTE_GZIP_SHA
         and type(capture_raw) is bytes and len(capture_raw)==2197 and sha(capture_raw)==CAPTURE_SHA,
         'EXACT_WHOLE_GZIP_AND_CAPTURE_PREIMAGES')
    capture=parse(capture_raw);validate_capture(capture)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw=stream.read(474)
    need(len(raw)==473 and sha(raw)==QUOTE_RAW_SHA,'EXACT_DECOMPRESSED_PROVIDER_PREIMAGE')
    value=parse(raw);reject_credentials(value)
    need(set(value)=={'bars','next_page_token'} and value['next_page_token'] is None
         and set(value['bars'])=={'BMY','BMY.RT'},'EXACT_COMPLETE_RESPONSE_IDENTITIES')
    for symbol,rows in value['bars'].items():
        need(type(rows) is list and len(rows)==2
             and [row['t'] for row in rows]==['2019-11-21T05:00:00Z','2019-11-22T05:00:00Z'],
             'EXACT_RETAINED_TWO_SESSION_BARS')
        for row in rows:
            need(set(row)=={'c','h','l','n','o','t','v','vw'},'EXACT_BAR_FIELDS')
            need(all(type(row[key]) in (int,Decimal) and Decimal(row[key]).is_finite()
                     and row[key]>0 for key in ('c','h','l','o','vw'))
                 and type(row['n']) is int and row['n']>=0
                 and type(row['v']) in (int,Decimal) and row['v']>=0,'FINITE_RAW_BAR_VALUES')
    row=value['bars']['BMY.RT'][0]
    return Quote(identity=Identity(),raw_open=str(row['o']),raw_close=str(row['c']))


def model_dict(model):
    return model.model_dump(mode='json',by_alias=True)


def validate_descriptor(value):
    need(type(value) is dict and set(value)==PUBLIC_KEYS,'EXACT_PUBLIC_DESCRIPTOR_FIELDS')
    return PublicDescriptor.model_validate(value)


def fresh_root(root):
    root=private_path(root)
    need(not root.exists() and not root.is_symlink(),'FRESH_DISJOINT_INPUT_DESTINATION')
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    return root


def write_new(path,raw):
    need(not path.exists() and not path.is_symlink(),'NEW_PRIVATE_OUTPUT_ONLY')
    with path.open('xb') as stream:
        os.chmod(path,0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())


def read_bounded(path,maximum):
    path=private_path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size<=maximum,'BOUNDED_REGULAR_INPUT_FILE')
    return path.read_bytes()


def unpack_authenticated(root,selected):
    expected=CapsuleManifest.model_validate(dict(schema='research.p01-celg-captured-inputs/1',
        authority='CAPTURED_MARKET_INPUT_ONLY_NOT_FINANCIAL_ADMISSION',
        provenance=model_dict(selected.provenance),members=MEMBERS))
    found={};manifest_raw=None;logical_end=0
    with tarfile.open(root/'capsule.tar','r:') as archive:
        for index,item in enumerate(archive):
            seal.safe_name(item.name)
            need(item.type==tarfile.REGTYPE and not item.linkname and not item.pax_headers
                 and 0<=item.size<=EXPANDED_MAX,
                 'ONLY_BOUNDED_REGULAR_ARCHIVE_MEMBERS')
            logical_end=item.offset_data+((item.size+511)//512)*512
            if index==0:
                need(item.name=='manifest.json' and item.size<=8192,'FIRST_BOUNDED_MANIFEST')
                manifest_raw=archive.extractfile(item).read(item.size+1)
                need(sha(manifest_raw)==selected.manifest_sha256,'EXACT_MANIFEST_PREIMAGE')
                manifest=CapsuleManifest.model_validate(parse(manifest_raw))
                need(model_dict(manifest)==model_dict(expected),'WHOLE_MANIFEST_AND_PROVENANCE')
            else:
                need(item.name in MEMBERS and item.name not in found,'EXACT_UNIQUE_TWO_FILE_INVENTORY')
                payload=archive.extractfile(item).read(item.size+1)
                need(dict(bytes=len(payload),sha256=sha(payload))==MEMBERS[item.name],
                     'ALL_MEMBER_PREIMAGES_BEFORE_ANY_PAYLOAD_PARSE')
                found[item.name]=payload
    need(manifest_raw is not None and set(found)==set(MEMBERS),'COMPLETE_TWO_FILE_INVENTORY')
    archive_raw=read_bounded(root/'capsule.tar',CAPSULE_MAX)
    need(len(archive_raw)%512==0 and len(archive_raw)>=logical_end+1024
         and not any(archive_raw[logical_end:]),'NO_UNDECLARED_TRAILING_ARCHIVE_PAYLOAD')
    quote=decode_payloads(found['quote.json.gz'],found['capture.json'])
    write_new(root/'manifest.json',manifest_raw)
    for name,payload in found.items():write_new(root/name,payload)
    return quote


def admit_cipher(root,selected,key):
    exact_crypto_sources()
    asset=root/selected.asset_name
    raw=read_bounded(asset,CAPSULE_MAX)
    need(len(raw)==selected.ciphertext_bytes and sha(raw)==selected.ciphertext_sha256
         and raw[:8]==seal.MAGIC,'EXACT_ORIGINAL_CRYPTO_FRAME_AND_CIPHERTEXT')
    seal.decrypt(asset,root/'capsule.tar',key,selected.ciphertext_sha256)
    unpack_authenticated(root,selected)
    header_hash=sha(raw[:20])
    body=dict(schema='research.p01-celg-input-authentication/1',authority=AUTHORITY,
        descriptor_sha256=digest(model_dict(selected)),ciphertext_sha256=selected.ciphertext_sha256,
        ciphertext_bytes=selected.ciphertext_bytes,manifest_sha256=selected.manifest_sha256,
        plaintext_tar_sha256=seal.sha256_file(root/'capsule.tar'),members=MEMBERS,
        header_sha256=header_hash,aad_sha256=header_hash,nonce_bytes=12,tag_bytes=16,
        actual_gcm_authenticated_before_parsing=True,all_inventory_preimages_verified=True,
        seal_source_sha256=SEAL_SHA,financial_input_admitted=False)
    write_new(root/'authentication.json',encoded(dict(body,sha256=digest(body))))
    return load_authenticated_input(root,model_dict(selected))


def authenticate_capsule(descriptor:dict,destination:Path,*,key:bytes)->AuthenticatedCelgInput:
    selected=validate_descriptor(descriptor);exact_crypto_sources()
    need(type(key) is bytes and len(key)==32,'RESEARCH_KEY_LENGTH')
    root=fresh_root(destination)
    asset=alpaca_fit_stage.acquire(selected.asset_name,
        dict(bytes=selected.ciphertext_bytes,sha256=selected.ciphertext_sha256),root)
    need(asset==root/selected.asset_name,'EXACT_NEW_CAPSULE_DOWNLOAD_PATH')
    return admit_cipher(root,selected,key)


def load_authenticated_input(root:Path,descriptor:dict)->AuthenticatedCelgInput:
    selected=validate_descriptor(descriptor);root=private_path(root)
    need(root.is_dir() and not root.is_symlink()
         and {path.name for path in root.iterdir()}=={selected.asset_name,'capsule.tar',
              'manifest.json','quote.json.gz','capture.json','authentication.json'}
         and all(path.is_file() and not path.is_symlink() for path in root.iterdir()),
         'EXACT_AUTHENTICATED_INPUT_DIRECTORY')
    cipher=read_bounded(root/selected.asset_name,CAPSULE_MAX)
    need(len(cipher)==selected.ciphertext_bytes and sha(cipher)==selected.ciphertext_sha256
         and cipher[:8]==seal.MAGIC,'RETAINED_EXACT_CIPHERTEXT_AND_HEADER')
    proof=parse(read_bounded(root/'authentication.json',8192))
    body={key:value for key,value in proof.items() if key!='sha256'}
    expected=dict(schema='research.p01-celg-input-authentication/1',authority=AUTHORITY,
        descriptor_sha256=digest(model_dict(selected)),ciphertext_sha256=selected.ciphertext_sha256,
        ciphertext_bytes=selected.ciphertext_bytes,manifest_sha256=selected.manifest_sha256,
        plaintext_tar_sha256=seal.sha256_file(root/'capsule.tar'),members=MEMBERS,
        header_sha256=sha(cipher[:20]),aad_sha256=sha(cipher[:20]),nonce_bytes=12,tag_bytes=16,
        actual_gcm_authenticated_before_parsing=True,all_inventory_preimages_verified=True,
        seal_source_sha256=SEAL_SHA,financial_input_admitted=False)
    need(body==expected and body['actual_gcm_authenticated_before_parsing'] is True
         and body['all_inventory_preimages_verified'] is True and body['financial_input_admitted'] is False
         and type(body['nonce_bytes']) is int and type(body['tag_bytes']) is int
         and proof.get('sha256')==digest(body),'WHOLE_AUTHENTICATION_RECEIPT_AND_PREIMAGES')
    manifest_raw=read_bounded(root/'manifest.json',8192)
    need(sha(manifest_raw)==selected.manifest_sha256,'RETAINED_MANIFEST_PREIMAGE')
    manifest=CapsuleManifest.model_validate(parse(manifest_raw))
    need(model_dict(manifest.provenance)==model_dict(selected.provenance),'RETAINED_ENTIRE_MANIFEST_PROVENANCE')
    payloads={name:read_bounded(root/name,item['bytes']) for name,item in MEMBERS.items()}
    need(all(dict(bytes=len(payloads[name]),sha256=sha(payloads[name]))==item for name,item in MEMBERS.items()),
         'RETAINED_WHOLE_INPUT_PREIMAGES')
    quote=decode_payloads(payloads['quote.json.gz'],payloads['capture.json'])
    identity=dict(manifest_sha256=selected.manifest_sha256,provenance=model_dict(selected.provenance),members=MEMBERS)
    return AuthenticatedCelgInput(quote,QUOTE_GZIP_SHA,QUOTE_RAW_SHA,CAPTURE_SHA,
        selected.manifest_sha256,selected.ciphertext_sha256,digest(identity))


def prepare_capsule(quote_path,capture_path,destination,*,key:bytes,existing_cipher:Path|None=None):
    exact_crypto_sources()
    quote_path=private_path(quote_path);capture_path=private_path(capture_path)
    compressed=read_bounded(quote_path,263);capture=read_bounded(capture_path,2197)
    decode_payloads(compressed,capture)
    need(type(key) is bytes and len(key)==32,'RESEARCH_KEY_LENGTH')
    root=fresh_root(destination)
    manifest=CapsuleManifest.model_validate(dict(schema='research.p01-celg-captured-inputs/1',
        authority='CAPTURED_MARKET_INPUT_ONLY_NOT_FINANCIAL_ADMISSION',provenance=provenance(),members=MEMBERS))
    pending=root/'pending-celg-input.tar.crseal'
    if existing_cipher is None:
        manifest_sha=local_stage.pack_data(pending,key,{'quote.json.gz':quote_path,'capture.json':capture_path},model_dict(manifest))
    else:
        retained=read_bounded(private_path(existing_cipher),CAPSULE_MAX)
        write_new(pending,retained)
        manifest_sha=sha(encoded(model_dict(manifest)))
    cipher_sha=seal.sha256_file(pending);name='p01-celg-input-'+cipher_sha+'.tar.crseal';asset=root/name
    need(pending.resolve().parent==root.resolve() and asset.resolve().parent==root.resolve()
         and not asset.exists(),'EXACT_NEW_CIPHERTEXT_RENAME_WITHIN_CAPSULE_DIRECTORY')
    pending.rename(asset)
    selected=PublicDescriptor.model_validate(dict(schema='research.p01-celg-input-capsule/1',repository=REPOSITORY,
        release=RELEASE,asset_name=name,asset_url=f'https://github.com/{REPOSITORY}/releases/download/{RELEASE}/'+name,
        ciphertext_bytes=asset.stat().st_size,ciphertext_sha256=cipher_sha,manifest_sha256=manifest_sha,provenance=provenance()))
    local=fresh_root(root/'local-authentication')
    shutil.copyfile(asset,local/name)
    result=admit_cipher(local,selected,key)
    write_new(root/DESCRIPTOR,encoded(model_dict(selected)))
    write_new(root/'preparation.json',encoded(dict(schema='research.p01-celg-input-local-preparation/1',
        status='EXACT_CAPTURED_CIPHER_LOCALLY_GCM_AND_FULL_INVENTORY_VERIFIED_NOT_UPLOADED',
        descriptor_sha256=digest(model_dict(selected)),ciphertext_sha256=cipher_sha,
        ciphertext_bytes=asset.stat().st_size,manifest_sha256=manifest_sha,
        input_identity_sha256=result.input_identity_sha256,actual_local_crypto_verified=True,
        original_crypto_protocol_sha256=CRYPTO_PROTOCOL,consumer_financial_protocol_sha256=CONSUMER_PROTOCOL,
        existing_cipher_reused_without_resealing=existing_cipher is not None,
        cloud_uploaded=False,provider_queried=False,financial_runtime_executed=False,financial_input_admitted=False)))
    return model_dict(selected)


def main():
    parser=argparse.ArgumentParser()
    for name in ('quote','capture','destination','key-dpapi'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--existing-cipher',type=Path)
    args=parser.parse_args()
    decode_payloads(read_bounded(args.quote,263),read_bounded(args.capture,2197))
    key_path=private_path(args.key_dpapi)
    need(key_path.name=='key.dpapi' and key_path.is_file()
         and not key_path.is_symlink(),'EXISTING_RESEARCH_DPAPI_KEY_REFERENCE')
    key=local_stage.dpapi(key_path.read_bytes(),unprotect=True)
    try:
        value=prepare_capsule(args.quote,args.capture,args.destination,key=key,existing_cipher=args.existing_cipher)
    finally:
        key=None
    print(json.dumps(dict(status='CELG_INPUT_CIPHER_PREPARED_NOT_UPLOADED',descriptor=str(args.destination/DESCRIPTOR),
        asset_name=value['asset_name'],ciphertext_bytes=value['ciphertext_bytes'],
        ciphertext_sha256=value['ciphertext_sha256'],manifest_sha256=value['manifest_sha256'])))


if __name__=='__main__':
    main()
