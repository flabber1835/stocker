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
    hashes,rows,raw=u.retained_seed(old,cp,p.root_spec('P07'))
    assert len(hashes)==6 and len(rows)==321 and rows[-1]['session']=='2021-01-29'
