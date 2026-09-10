"""Regressions for independent economics, field sensitivity and source vintages."""
import ast
import copy
import json
from pathlib import Path

import httpx
import pytest

from research.sharadar_replay.model import Revision
from research.sharadar_replay.oracle import StateMismatch, compare
from research.sharadar_replay.provider import Provider
from research.sharadar_replay.runtime import simulated_runtime
from research.sharadar_replay.scenarios import FIRST, DIVIDEND, OLD_CORRECTION, SID, build_scenarios, step, world
from research.sharadar_replay.verify_evidence import CATALOGUE


@pytest.mark.parametrize('factor', [0.25, 0.5, 2, 4, 10])
def test_combined_raw_economics_and_adjusted_encoding(factor):
    tables, expected = world(FIRST, split=True, split_factor=factor, correction=104, dividend=1)
    source = next(r for r in tables['SEP'] if r['ticker']=='AAA' and r['date']==OLD_CORRECTION)
    bar = next(r for r in expected.bars if r[:2]==('SIM-AAA', OLD_CORRECTION))
    cash = next(r for r in tables['ACTIONS'] if r['ticker']=='AAA' and r['action']=='dividend')
    raw_cash = next(r[8] for r in expected.bars if r[:2]==('SIM-AAA', DIVIDEND))
    assert source['close'] == bar[3] == 104 / factor
    assert bar[4] == 104
    assert cash['value'] == 1 / factor
    assert raw_cash == 1


def test_original_combined_oracle_errors_are_killed():
    _, expected = world(FIRST, split=True, correction=104, dividend=1)
    for field, day, wrong in [(3, OLD_CORRECTION, 50), (8, DIVIDEND, 2)]:
        rows = []
        for row in expected.bars:
            changed = list(row)
            if row[:2] == ('SIM-AAA', day):
                changed[field] = wrong
            rows.append(tuple(changed))
        with pytest.raises(StateMismatch, match='bars'):
            compare(expected, expected.model_copy(update={'bars': tuple(rows)}))


def test_fixture_distinguishes_price_domains_and_changing_volume():
    tables, expected = world(FIRST, split=True)
    assert all(r[4] != r[5] for r in expected.bars)
    assert len({r[6] for r in expected.bars}) > 100
    assert all(len({r[k] for k in ('open', 'close', 'closeadj', 'closeunadj')}) == 4
               for r in tables['SFP'])
    assert len({r[1] for r in expected.spy}) > 100
    damaged = expected.model_copy(update={'bars':tuple((*r[:5], r[4], *r[6:]) for r in expected.bars)})
    with pytest.raises(StateMismatch, match='bars'):
        compare(expected, damaged)


def test_committed_catalogue_matches_factory_and_falsifiers():
    declared = json.loads(CATALOGUE.read_text())
    scenarios = build_scenarios()
    assert declared['scenarios'] == {name: [s.seed.name, *(step.name for step in s.steps)]
                                     for name, s in scenarios.items()}
    path = Path(__file__).with_name('test_postgres.py')
    names = [node.name for node in ast.parse(path.read_text()).body
             if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
             and node.name != 'test_daily_production_replay']
    # Parametrized field falsifiers have explicit expanded IDs in the catalogue.
    actual = {name.split('[')[0] for name in declared['required_tests']}
    assert actual == {f'research/sharadar_replay/tests/test_postgres.py::{name}' for name in names}


@pytest.mark.parametrize('name', ['sep_between_observations', 'sep_during_pagination'])
def test_source_revisions_change_complete_observations_reproducibly(name):
    from sentinel.feed import authority, sharadar
    scenario = build_scenarios()[name]
    transcripts = []
    for _ in range(2):
        provider = Provider(page_size=scenario.page_size)
        provider.advance(scenario.steps[0])
        params = dict(scenario.steps[0].revisions[0].query)
        with simulated_runtime(provider, commit='a' * 40):
            first = list(sharadar.fetch_table('SEP', params))
            second = list(sharadar.fetch_table('SEP', params))
        with pytest.raises(authority.VendorPublicationUnstable):
            authority.require_stable('SEP', authority.observe_sep(first), authority.observe_sep(second))
        provider.assert_revisions_applied()
        transcripts.append(provider.transcript)
    assert transcripts[0] == transcripts[1]
    activations = [r for r in transcripts[0] if r['activated_revisions']]
    assert len(activations) == 1
    revision = scenario.steps[0].revisions[0]
    assert (activations[0]['observation'], activations[0]['offset']) == (revision.observation, revision.after_rows)


def test_unreached_revision_is_a_failing_scenario():
    provider = Provider()
    current = step('source', FIRST)
    revision = Revision(name='never_reached', table='SEP', observation=99, rows=current.tables['SEP'])
    provider.advance(current.model_copy(update={'revisions': (revision,)}))
    with pytest.raises(AssertionError, match='never activated'):
        provider.assert_revisions_applied()


def test_export_download_retains_issued_vintage_after_revision():
    provider = Provider()
    current = step('source', FIRST)
    changed = copy.deepcopy(current.tables['SFP'])
    changed[0]['closeadj'] += 1
    revision = Revision(name='new_sfp_export', table='SFP', channel='export', rows=changed)
    provider.advance(current.model_copy(update={'revisions': (revision,)}))
    request = httpx.Request('GET', 'https://data.nasdaq.com/api/v3/datatables/SHARADAR/SFP.json?qopts.export=true')
    first_url = provider(request).json()['datatable_bulk_download']['file']['link']
    first_bytes = provider(httpx.Request('GET', first_url)).content
    second_url = provider(request).json()['datatable_bulk_download']['file']['link']
    assert second_url != first_url
    assert provider(httpx.Request('GET', first_url)).content == first_bytes
    assert provider(httpx.Request('GET', second_url)).content != first_bytes
    provider.assert_revisions_applied()
