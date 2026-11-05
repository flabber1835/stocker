"""Registered legal-unit input compiler; no price repair or state mutation."""
from copy import deepcopy
import csv
from dataclasses import fields,replace
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

from p01_iac_unit_contract import (SOURCE,EVENT,END,SCHEMA,UnitInput,document,parse,facts,unique,
    need,sha,digest)
from p01_iac_unit_parent import OUTER,STATE
from system_campaign_discovery_context import material


def number(value):return None if value is None or value=='' else float(value)


def forward(native_factor,combined_factor,native_split,*,unit_event=False):
    """Exact frozen forward sequence: factors first, then a caller's raw price."""
    native_factor*=float(native_split)
    combined_factor*=float(native_split)
    if unit_event:combined_factor*=float('2.1584')
    return native_factor,combined_factor


class NativeDomain:
    """Pure chronological input derivation; no canonical run is constructed."""
    def __init__(self,rows,normalizer):
        self.rows={};self.days={};self.failures={}
        self.original_multiplier=float.fromhex(normalizer['original_signal_multiplier_hex'])
        native=float.fromhex(normalizer['initial_native_factor_hex'])
        combined=float.fromhex(normalizer['initial_combined_factor_hex'])
        need(native==combined==self.original_multiplier==1.0,'EXACT_QUALIFIED_ORIGINAL_UNIT_BASIS')
        need(all(rows[i]['session']<rows[i+1]['session'] for i in range(len(rows)-1)),
             'SOURCE_NATIVE_CSV_ORDER_MUST_BE_STRICT_WITHOUT_SORTING')
        previous=None;blocked=False
        for row in rows:
            day=row['session']
            need(row['security_id']==SOURCE and day not in self.rows,'UNIQUE_DATED_SOURCE_DOMAIN')
            self.rows[day]=deepcopy(row)
            if day<EVENT:continue
            if blocked:self.failures[day]='EARLIER_NATIVE_BASIS_REFUSAL';continue
            try:
                need(previous is not None or day==EVENT,'FIRST_SOURCE_UNIT_EVENT_ROW_REQUIRED')
                s=number(row['split_ratio']);raw=number(row['raw_close']);published=number(row['signal_close'])
                need(s is not None and math.isfinite(s) and s>0,'FINITE_POSITIVE_NATIVE_SPLIT_REQUIRED')
                need(day!=EVENT or s==1.0,'UNQUALIFIED_COINCIDENT_NATIVE_SPLIT_AT_RECLASSIFICATION')
                native,combined=forward(native,combined,s,unit_event=day==EVENT)
                need(math.isfinite(native) and native>0 and math.isfinite(combined) and combined>0,'FINITE_FORWARD_FACTORS')
                if raw is None or published is None:
                    need(day!=EVENT and raw is published is None,'NO_MIXED_OR_EVENT_MISSING_SOURCE_PRICE')
                    logical=None
                else:
                    need(math.isfinite(raw) and raw>=0 and math.isfinite(published) and published>=0
                         and published*self.original_multiplier==raw*native,'UNKNOWN_NATIVE_SIGNAL_RAW_SPLIT_BASIS')
                    need(day!=EVENT or raw>0 and published>0 and number(row['raw_compatible_volume'])>0,
                         'EVENT_REQUIRES_ACTUAL_CURRENT_POSITIVE_VOLUME_PRICE')
                    logical=raw*combined
                    need(math.isfinite(logical),'FINITE_LOGICAL_SIGNAL_REQUIRED')
                self.days[day]=dict(session=day,native_factor_hex=native.hex(),combined_factor_hex=combined.hex(),
                    logical_signal_close=logical,effective_split_ratio=s*float('2.1584') if day==EVENT else s,
                    raw_row_sha256=digest(row),native_basis_exact=True,canonical_factor_then_raw_order=True,
                    legal_factor_insertions=1)
                previous=day
            except (ValueError,TypeError,OverflowError) as exc:
                self.failures[day]=str(exc);blocked=True


def source_rows(*,through=END,archive=Path('/frozen/archive/corpus.zip')):
    from full_system_core import hosted
    hosted();value=facts();rows=[];members={}
    with zipfile.ZipFile(archive) as z:
        raw=z.read('manifest.json')
        need(dict(bytes=len(raw),sha256=sha(raw))==value['source_manifest'],'EXACT_ADMITTED_SOURCE_MEMBER_MANIFEST')
        for year in range(2020,int(through[:4])+1):
            name=f'observations-{year}.csv.gz';expected=value['source_members'][name];info=z.getinfo(name);h=hashlib.sha256()
            with z.open(name) as stream:
                for chunk in iter(lambda:stream.read(1024**2),b''):h.update(chunk)
            need(info.file_size==expected['bytes'] and h.hexdigest()==expected['sha256'],'EXACT_NORMALIZER_OBSERVATION_MEMBER')
            count=0;selected=[]
            with z.open(name) as compressed,gzip.GzipFile(fileobj=compressed) as inflated,io.TextIOWrapper(inflated,encoding='utf8',newline='') as text:
                for row in csv.DictReader(text):
                    count+=1
                    if row['security_id']==SOURCE and row['session']<=through:
                        rows.append(row);selected.append(dict(session=row['session'],sha256=digest(row)))
            need(count==expected['rows'],'EXACT_NORMALIZER_MEMBER_ROW_COUNT')
            need(all(selected[i]['session']<selected[i+1]['session'] for i in range(len(selected)-1)),
                 'EXACT_SOURCE_ROW_CSV_ORDER_NOT_REPAIRED_BY_SORTING')
            members[name]=dict(**deepcopy(expected),selected_source_rows=len(selected),
                selected_source_original_order_sha256=digest(selected),selected_order_strict_increasing=True)
    return rows,members


def validate_origin(parent):
    value=facts();series=parent['run']['state']['feed']['series'][SOURCE];normalizer=value['normalizer']
    need(parent['sha256']==OUTER and parent['completed']==628 and parent['source_cursor']=='2020-06-30'
         and parent['run']['state_sha256']==STATE and digest(series)==normalizer['original_source_series_sha256']
         and float(series['split_factor']).hex()==normalizer['initial_native_factor_hex']
         and series.get('signal_basis_multiplier',1.0)==series.get('vendor_basis_multiplier',1.0)==1.0
         and series['signal_basis_anchor'][0]==parent['source_cursor']
         and series['signal_basis_anchor'][1]==series['signal_basis_anchor'][2],
         'EXACT_ADMITTED628_ANCHOR_AND_SOURCE_BOUND_DEFAULT_BASIS')
    return deepcopy(series)


class InputCodec:
    def __init__(self,rows,parent):
        self.expected=document();self.records=facts();self.origin=validate_origin(parent)
        self.domain=NativeDomain(rows,self.records['normalizer']);self.objects=[];self.registered={}
        self.applied=[];self.refusals={};self.control=False;self.controls=[]

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes(),object_pairs_hook=unique).get('schema')!=SCHEMA:
            return self.original_load(path,resume_session=resume_session,
                predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj=parse(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        self.objects.append(obj)
        self.registered[obj.sha256]=obj.model_dump(mode='json',by_alias=True)
        return obj

    def is_registered(self,loaded):
        return (isinstance(loaded,UnitInput) and type(loaded.sha256) is str
            and loaded.sha256 in self.registered
            and loaded.model_dump(mode='json',by_alias=True)==self.registered[loaded.sha256]==self.expected)

    def refusal(self,packet,code):
        row=dict(session=packet.day,reason=code,native_packet_sha256=digest(material(packet)),
            packet_left_unchanged=True,financial_advance_authorized=False)
        self.refusals[packet.day]=row;return packet

    def apply(self,packet,loaded):
        if not isinstance(loaded,UnitInput):return self.original_apply(packet,loaded)
        need(self.is_registered(loaded),'EXACT_REGISTERED_TYPED_TWELFTH_DESCRIPTOR_AND_FULL_MODEL')
        day=packet.day
        if day<EVENT:return packet
        matching=[b for b in packet.bars if b.security_id==SOURCE]
        if not matching and day!=EVENT and day not in self.domain.rows:return packet
        if len(matching)!=1:return self.refusal(packet,'UNIT_SOURCE_CURRENT_BAR_ABSENT_OR_DUPLICATED')
        if day in self.domain.failures:return self.refusal(packet,self.domain.failures[day])
        if day not in self.domain.days:return self.refusal(packet,'OUTSIDE_COMPILED_SOURCE_BASIS')
        from research.bounded_20y.run import vendor
        bar=matching[0];entry=self.domain.days[day];row=self.domain.rows[day]
        if material(bar)!=material(vendor(row)):return self.refusal(packet,'POST_OLD11_NATIVE_SOURCE_BAR_PREIMAGE_CHANGED')
        transformed=replace(bar,signal_close=entry['logical_signal_close'],split_ratio=entry['effective_split_ratio'])
        before=material(bar);after=material(transformed)
        need({k:v for k,v in before.items() if k not in ('signal_close','split_ratio')}
             =={k:v for k,v in after.items() if k not in ('signal_close','split_ratio')},'ONLY_DECLARED_UNIT_DOMAIN_FIELDS')
        changed=replace(packet,bars=tuple(transformed if b is bar else b for b in packet.bars))
        need(all(getattr(packet,f.name) is getattr(changed,f.name) for f in fields(packet) if f.name!='bars')
             and all(b is c for b,c in zip(packet.bars,changed.bars) if b.security_id!=SOURCE),
             'ALL_OTHER_PACKET_QUOTE_IDENTITY_CASH_SPIN_FIELDS_UNCHANGED')
        proof=dict(**entry,native_bar=before,logical_bar=after,native_source_metadata=material(packet.meta.get(SOURCE)),
            child_or_cash_value_added=False,all_raw_price_volume_and_other_fields_unchanged=True,
            source_preimage_authenticated=True,derivation_before_buffer_append=True)
        (self.controls if self.control else self.applied).append(proof)
        return changed

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest,repair
        self.backtest,self.repair=backtest,repair
        self.original_load,self.saved_load=repair.load_repair,backtest.load_repair
        self.original_apply=backtest.apply_repair
        repair.load_repair=backtest.load_repair=self.load;backtest.apply_repair=self.apply
        return self

    def __exit__(self,*args):
        self.repair.load_repair=self.original_load;self.backtest.load_repair=self.saved_load
        self.backtest.apply_repair=self.original_apply
