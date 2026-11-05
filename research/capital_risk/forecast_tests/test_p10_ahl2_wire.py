"""Wrong kind, gzip truncation/CRC/size and exact identity preimage falsifiers."""
import ast
from copy import deepcopy
import gzip
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import system_campaign_p10_ahl2_contract as c
import system_campaign_p10_ahl2_wire as wire
import system_campaign_p10_ahl2_input as input4


def test_plain_and_declared_gzip_object_positive():
    raw=b'{"synthetic":true}\n'
    assert wire.object_bytes(raw)==wire.object_bytes(gzip.compress(raw),gzip_declared=True)=={'synthetic':True}


@pytest.mark.parametrize('raw,declared',[(gzip.compress(b'{}'),False),(b'{}',True),
    (b'{"x":1,"x":2}',False),(b'{"x":NaN}',False),(b'[]',False),(b'\xff',False)])
def test_json_kind_and_structure_refuse(raw,declared):
    with pytest.raises((ValueError,UnicodeDecodeError)):
        wire.object_bytes(raw,gzip_declared=declared)


@pytest.mark.parametrize('bad',[
    lambda x:x[:-1],lambda x:x+b'trailer',lambda x:x+gzip.compress(b'{}'),
    lambda x:x[:-8]+bytes([x[-8]^1])+x[-7:]])
def test_complete_single_crc_checked_gzip_only(bad):
    with pytest.raises(ValueError):wire.object_bytes(bad(gzip.compress(b'{}')),gzip_declared=True)


def test_expansion_and_compressed_bounds_refuse():
    raw=gzip.compress(b'{"large":"'+b'x'*1000+b'"}')
    with pytest.raises(ValueError,match='P10_GZIP_EXPANDED_BOUND'):wire.inflate(raw,expanded_limit=100)
    with pytest.raises(ValueError,match='P10_DECLARED_GZIP_HEADER_AND_COMPRESSED_BOUND'):
        wire.inflate(raw,compressed_limit=len(raw)-1)


def test_actual_compressed_bound_removal_falsifier():
    raw=gzip.compress(b'{}')
    with pytest.raises(ValueError):wire.inflate(raw,compressed_limit=1)
    fn=c.function((HERE/'system_campaign_p10_ahl2_wire.py').read_bytes(),'inflate')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Compare(self,node):
            if ast.unparse(node)=='len(raw) <= compressed_limit':
                self.count+=1
                return ast.copy_location(ast.Constant(True),node)
            return self.generic_visit(node)
    transform=Remove();fn=transform.visit(fn);assert transform.count==1
    ns=dict(vars(wire))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-compressed-bound>','exec'),ns)
    assert ns['inflate'](raw,compressed_limit=1)==b'{}'


def identity_fixture():
    witness=deepcopy(c.specification()['identity_witness'])
    row={k:v for k,v in witness.items() if k!='source_observation_sha256'}
    row['raw_close']='SYNTHETIC_SOURCE_FIELD'
    witness['source_observation_sha256']=c.digest(row)
    return row,witness


def test_exact_raw_identity_preimage_preserves_unknown_classification():
    row,witness=identity_fixture();input4.identity_valid(row,witness)
    row['issuer_id']='SEC_CIK:NEW_NOT_ADMITTED'
    with pytest.raises(ValueError):input4.identity_valid(row,witness)


def test_actual_source_preimage_predicate_removal_falsifier():
    row,witness=identity_fixture();row['raw_close']='CHANGED_SOURCE_FIELD'
    with pytest.raises(ValueError):input4.identity_valid(row,witness)
    fn=c.function((HERE/'system_campaign_p10_ahl2_input.py').read_bytes(),'identity_valid')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Compare(self,node):
            if ast.unparse(node)=="digest(row) == witness['source_observation_sha256']":
                self.count+=1
                return ast.copy_location(ast.Constant(True),node)
            return self.generic_visit(node)
    transform=Remove();fn=transform.visit(fn);assert transform.count==1
    ns=dict(vars(input4))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-source-row-hash>','exec'),ns)
    ns['identity_valid'](row,witness)
