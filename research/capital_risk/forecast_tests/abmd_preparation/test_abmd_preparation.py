"""Actual typed input resource with clearly synthetic packet/native DTO classes."""
import json,sys
from copy import deepcopy
from dataclasses import dataclass,make_dataclass,replace,asdict
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_abmd_bounded_preparation as prep
from system_campaign_bounded_sensor_input import InputCodec,parse
from system_campaign_abmd_bounded_catalog import document,evidence,encoded

@dataclass(frozen=True)
class SyntheticPacket:
    day:str
    bars:tuple
    terminal:tuple

@pytest.fixture
def actual(tmp_path):
    c=json.loads((Path(__file__).resolve().parents[2]/'P07-own1238-ABMD-bounded-catalog-v2.json').read_bytes());n=c['native']
    Native=make_dataclass('SyntheticNativeDTO',[(k,object) for k in n],frozen=True)
    Native.completeness=lambda self,count:(self.cash_per_share is not None,())
    native=Native(**n);codec=InputCodec(c['event'],evidence(c),native)
    path=tmp_path/'synthetic-input-resource.json';path.write_bytes(encoded(document(c)))
    obj=codec.load(path,resume_session='2022-11-30',predecessor_checkpoint_sha256=c['parent_inner_sha256'])
    return c,native,codec,obj,path

def test_actual_typed_parser_recalendars_only_terminal_and_preserves_native_bar(actual):
    c,native,codec,obj,path=actual;bar=deepcopy(c['market_source']['raw_prior_row'])
    before=SyntheticPacket('2022-12-21',(bar,),(native,));after=codec.apply(before,obj)
    assert after.day==before.day and after.bars==before.bars and after.bars[0] is before.bars[0]
    assert after.terminal==() and before.terminal==(native,)
    closing=SyntheticPacket('2022-12-22',(),());fixed=codec.apply(closing,obj)
    assert fixed.bars==() and fixed.terminal==(replace(native,session='2022-12-22'),)
    assert fixed.terminal[0].cash_per_share is None and not fixed.terminal[0].completeness(0)[0]

@pytest.mark.parametrize('change',['predecessor','consumed'])
def test_wrong_predecessor_and_consumed_native_cursor_refuse(actual,change):
    c,native,codec,obj,path=actual
    with pytest.raises(ValueError):
        parse(path,resume_session='2022-12-21' if change=='consumed' else '2022-11-30',
            predecessor_checkpoint_sha256='0'*64 if change=='predecessor' else c['parent_inner_sha256'],
            expected_event=c['event'],expected_evidence=evidence(c))

@pytest.mark.parametrize('change',['wrong_native','effective_collision','uncommitted_object'])
def test_packet_preimage_collision_or_uncommitted_model_refuses(actual,change):
    c,native,codec,obj,path=actual
    if change=='wrong_native':packet=SyntheticPacket('2022-12-21',(),(replace(native,reference='FOREIGN'),))
    elif change=='effective_collision':packet=SyntheticPacket('2022-12-22',(),(replace(native,session='2022-12-22'),))
    else:codec.objects=[];packet=SyntheticPacket('2022-12-21',(),(native,))
    with pytest.raises(ValueError):codec.apply(packet,obj)

@pytest.mark.parametrize('name',['prepare','qualify_packets'])
def test_hosted_helpers_refuse_before_any_local_financial_import(monkeypatch,name):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        if name=='prepare':prep.prepare({},None,{},catalog_path=None,catalog_sha256='0'*64)
        else:prep.qualify_packets({},None,None,None,{})
