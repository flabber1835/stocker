"""Shared original literal selector and own775 retained proof seed; no replay."""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_partial as p
import system_campaign_financial_uncertainty as u


def test_p07_775_selects_complete_original_following_catalog_without_alias_refetch():
    codec,name,terms=f.selected('P07',cursor='2021-01-29')
    original=json.loads((f.HERE/name).read_bytes())
    assert terms==original['terms'] and len(terms)==6
    assert [t['ticker'] for t in terms]==['ACIA','APHA','CATM','AZPN1','REGI','PLAN']
    assert terms[0]['added']['cash_per_share']==115. and terms[0]['added']['session']=='2021-03-01'
    assert ('P07','2021-01-29') not in f.FOLLOWING_PHASES
    assert terms[3]['frozen_provider_issuer_limitation']==original['terms'][3]['frozen_provider_issuer_limitation']
    cp=dict(source_cursor='2021-01-29',run=dict(checkpoint_sha256='a'*64))
    assert len(f.suppressions(cp,terms))==6


def test_actual775_seed_keeps_only321_committed_certificates():
    old=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-153/capture-P07-13351766786-002/verified-output')
    if not old.exists():
        import pytest
        pytest.skip('private DATA fixture is local-only')
    import gzip
    old=Path('\\\\?\\'+str(old.resolve()));cp=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
    hashes,rows,raw=u.retained_seed(old,cp,p.root_spec('P07','672a0a0a7560d1b3d4658e6c0e79c3f4259391ac4a7f2d3ecb58e505f5132ef3'))
    assert len(hashes)==6 and len(rows)==321 and rows[-1]['session']=='2021-01-29'


def test_new817_selects_only_future_original2021_terms_and_keeps_its363_row_seed():
    spec=p.root_spec('P07');assert spec['measured_closes']==817
    codec,name,terms=f.selected('P07',cursor='2021-03-31')
    assert [t['ticker'] for t in terms]==['MIK','VAR','NAV','WORK','HOME','TRIL1']
    original=json.loads((f.HERE/name).read_bytes())
    assert terms==original['terms'][2:]
    assert terms[0]['added']['cash_per_share']==22. and terms[0]['added']['session']=='2021-04-15'
    old=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-173/capture-P07-13354352890-002/verified-output')
    if old.exists():
        import gzip
        old=Path('\\\\?\\'+str(old.resolve()));cp=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
        assert len(u.retained_seed(old,cp,spec)[1])==363


def test_cash_calendar_phase_for_p11_does_not_need_a_default_arm_plan(monkeypatch):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations
    monkeypatch.setattr(registry,'registrations',lambda:original(f.HERE))
    assert 'P11'not in f.PLANS
    a,name,terms=f.selected('P11',cursor='2022-01-31')
    b,other,prior=f.selected('P10',cursor='2022-01-31')
    assert name==other and terms==prior and a.catalog_sha==b.catalog_sha
    term,=terms
    assert term['ticker']=='VCRA' and term['native_session']=='2022-02-22'
    assert term['added']['session']=='2022-02-23' and term['added']['cash_per_share']==79.25
