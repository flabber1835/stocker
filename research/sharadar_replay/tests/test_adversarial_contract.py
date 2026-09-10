"""Independent adversarial transport and causal schedule checks."""
import httpx
import pytest

from research.sharadar_replay.model import Fault
from research.sharadar_replay.provider import Provider
from research.sharadar_replay.runtime import simulated_runtime
from research.sharadar_replay.scenarios import FIRST, build_scenarios, step
from research.sharadar_replay.oracle import digest


@pytest.mark.parametrize('table', ['TICKERS', 'ACTIONS', 'SEP', 'SFP'])
@pytest.mark.parametrize('kind', ['missing_column', 'row_width', 'missing_cursor', 'invalid_json'])
@pytest.mark.parametrize('after_rows', [0, 1])
def test_invalid_envelope_fails_even_after_valid_prefix(table, kind, after_rows):
    from sentinel.feed import sharadar
    provider = Provider(page_size=1)
    provider.advance(step('bad', FIRST, faults=(Fault(table=table, kind=kind, after_rows=after_rows),)))
    with simulated_runtime(provider, commit='a' * 40):
        with pytest.raises(sharadar.SharadarProtocolError):
            list(sharadar.fetch_table(table))
    assert len(provider.transcript) == after_rows + 1


@pytest.mark.parametrize('seed', [1, 2, 9, 16])
@pytest.mark.parametrize('page_size', [1, 7, 53, 1000])
def test_pagination_and_permutation_preserve_exact_source_multiset(seed, page_size):
    from sentinel.feed import sharadar
    provider = Provider(page_size=page_size, variation_seed=seed)
    current = step('source', FIRST)
    provider.advance(current)
    with simulated_runtime(provider, commit='a' * 40):
        actual = list(sharadar.fetch_table('SEP'))
    assert sorted(map(digest, actual)) == sorted(map(digest, current.tables['SEP']))


def test_seeded_schedules_reproduce_and_vary():
    first, second = build_scenarios(), build_scenarios()
    names = [n for n in first if n.startswith('seeded_revision_')]
    assert len(names) == 16
    assert [first[n].model_dump_json() for n in names] == [second[n].model_dump_json() for n in names]
    assert len({digest(first[n].steps[0].expected.model_dump()) for n in names}) >= 12
    assert all(first[n].variation_seed > 0 for n in names)


def test_provider_transcript_records_late_fault_activation():
    provider = Provider(page_size=1)
    provider.advance(step('prefix', FIRST, faults=(Fault(table='SEP', kind='http_400', after_rows=1),)))
    url = 'https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json'
    assert provider(httpx.Request('GET', url)).status_code == 200
    assert provider(httpx.Request('GET', url + '?qopts.cursor_id=1')).status_code == 400
    assert provider.transcript[0]['faults'] == []
    assert provider.transcript[1]['faults'] == ['http_400']


@pytest.mark.parametrize('value', ['Infinity', '-Infinity', 'NaN', float('inf'), float('-inf')])
def test_nonfinite_raw_prices_fail_production_coverage(value):
    from sentinel.feed import domains
    report = domains.NormalisationReport()
    rows = list(domains.normalise_sep_rows([dict(ticker='AAA', date=FIRST,
        open=100, close=100, closeunadj=value, volume=1000)], report=report))
    assert rows == []
    with pytest.raises(domains.RawPriceDomainUnavailable):
        domains.assert_raw_price_domain(report)


def test_old_infinite_price_parser_is_killed(monkeypatch):
    from sentinel.feed import domains
    original = domains._f
    monkeypatch.setattr(domains, '_f', lambda v: float('inf') if v == 'Infinity' else original(v))
    report = domains.NormalisationReport()
    list(domains.normalise_sep_rows([dict(ticker='AAA', date=FIRST,
        open=100, close=100, closeunadj='Infinity', volume=1000)], report=report))
    # The old parser advertises complete raw prices. The acceptance invariant kills it.
    with pytest.raises(AssertionError):
        assert report.raw_close_coverage < 0.9, 'non-finite input passed the coverage guard'


@pytest.mark.parametrize('other_rows', [1, 2, 100])
@pytest.mark.parametrize('kind', ['daily', 'actions_reconcile', 'sep_mutations'])
def test_metadata_recovery_exception_cannot_admit_other_pending_rows(monkeypatch, other_rows, kind):
    from types import SimpleNamespace
    from sentinel.feed import ingest_authority_impl, publication, recovery
    candidates = [recovery.FailedLiveCandidate(run_id='one', kind='daily'),
                  recovery.FailedLiveCandidate(run_id='two', kind=kind)]
    monkeypatch.setattr(recovery, 'failed_live_candidates', lambda conn: candidates)
    monkeypatch.setattr(publication, 'coherence', lambda conn: SimpleNamespace(
        unpublished_rows=2 + other_rows, unpublished_universe=2,
        unpublished_spy=0, unpublished_defensive=0))
    with pytest.raises(recovery.PublicationRecoveryRefused):
        ingest_authority_impl._single_failed_live_candidate(object())


def test_metadata_only_mixed_operation_kinds_remain_blocked(monkeypatch):
    from types import SimpleNamespace
    from sentinel.feed import ingest_authority_impl, publication, recovery
    monkeypatch.setattr(recovery, 'failed_live_candidates', lambda conn: [
        recovery.FailedLiveCandidate(run_id='one', kind='daily'),
        recovery.FailedLiveCandidate(run_id='two', kind='seed')])
    monkeypatch.setattr(publication, 'coherence', lambda conn: SimpleNamespace(
        unpublished_rows=2, unpublished_universe=2,
        unpublished_spy=0, unpublished_defensive=0))
    with pytest.raises(recovery.PublicationRecoveryRefused):
        ingest_authority_impl._single_failed_live_candidate(object())


@pytest.mark.parametrize('values', [
    dict(table='SEP', kind='invalid_zip'),
    dict(table='SEP', kind='missing_cursor', channel='export'),
    dict(table='SEP', kind='set_value'),
    dict(table='SEP', kind='omit_ticker'),
    dict(table='TICKERS', kind='conflicting_row'),
    dict(table='TICKERS', kind='missing_column', channel='export', after_rows=1),
])
def test_fault_contract_rejects_silently_inactive_configurations(values):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Fault(**values)
