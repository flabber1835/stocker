"""Historical cash knowledge can explain a warning but grants no financial authority."""
from copy import deepcopy
from contextvars import ContextVar
from datetime import date
import inspect

from psycopg.types.json import Jsonb
import pytest

from sentinel import informational_paper_mirror as mirror, mirror_projection
from sentinel.execution import feed_inputs, journal
from sentinel.feed import publication
from sentinel.feed.rolling_contract import digest
from sentinel.panel import mirror_history
from tests.sentinel.test_cash_correction_recovery import DAY, SID, classify, witness
from tests.sentinel.test_journal_and_reconcile import BBB, cmd
from tests.sentinel.test_mirror_dependency_projection import Plan, base_conn, bootstrap, conn, install, pg, publish


def row_for(witness):
    value = witness['marker']
    return dict(decision_session='2026-10-19', effective_session=DAY, security_ids=[SID], symbols=['DELL'],
                material_sha256=digest({SID: 'UNSUPPORTED:historycorrection:' + value['source_row_id']}))


def test_preexisting_latched_plans_explain_cash_and_report_actual_commands(conn, monkeypatch, witness):
    original = dict(witness['old_day'], publication_version=1)
    marker = dict(witness['marker'], publication_version=2)
    old = dict(basis='2026-10-01', through=DAY, added={DAY: digest(original)}, corrections=[])
    held = dict(basis=old['basis'], through=DAY, added={}, corrections=[marker],
                correction_evidence={DAY: witness['new_correction_day']})
    for version, cover in enumerate((old, held), 1):
        conn.execute('INSERT INTO sentinel_action_coverage VALUES(%s,%s,%s,%s,%s)',
                     (version, old['basis'], DAY, digest(cover), Jsonb(cover)))
        if version == 1:
            conn.execute('INSERT INTO sentinel_action_history VALUES(%s,%s,%s,%s)',
                         (DAY, version, digest(original), Jsonb(original)))
        publish(conn, version, evidence={'action_history': digest(cover)})
    plans = [Plan(f'cash-history-{i}', date(2026, 10, 19), date.fromisoformat(DAY)) for i in (1, 2)]
    for plan in plans:
        mirror.record_pending(conn, plan=plan, active_security_ids=[SID], active_symbols={SID: 'DELL'},
            sizing_authority_sha256='b'*64, shadow_record_sha256='c'*64, publication_version=1)
    journal.save_command(conn, cmd(plan=plans[0].plan_id))
    conn.commit()
    install(conn, monkeypatch)
    bootstrap(conn)
    # These are the original, signed /1 mirror rows. The deployment has no
    # explanation written by a new producer and the verifier uses a read-only transaction.
    for plan in plans:
        data = mirror_projection._row(conn, plan.plan_id)
        data.update(status=mirror.MISMATCH, historical_mismatch=True, checked_publication=2,
                    material_sha256=row_for(witness)['material_sha256'])
        mirror_projection._write(conn, data)
    conn.commit()
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    before = conn.execute('SELECT payload,hmac_sha256 FROM sentinel_paper_mirror_dependencies ORDER BY plan_id').fetchall()
    pub = publication.require_current(conn)
    monkeypatch.setattr(feed_inputs, 'is_rolling', lambda p: p == pub)
    memo = mirror_history.ClassificationMemo()
    monkeypatch.setattr(mirror_history, 'current_memo', ContextVar('test_mirror_memo', default=memo))
    classify_calls = []
    row_reads = []
    canonical = mirror_history._classify
    load_row = mirror_projection._row
    def counted(*args):
        classify_calls.append(True)
        return canonical(*args)
    monkeypatch.setattr(mirror_history, '_classify', counted)
    monkeypatch.setattr(mirror_projection, '_row',
        lambda conn, plan_id: row_reads.append(plan_id) or load_row(conn, plan_id))
    summary = dict(historical_mismatch_count=2, indexed_history_publication=2, indexed_history_context='a'*64)
    detail = mirror_history.detail(conn, pub, summary)
    assert 'Late dividend data explains the latest check on 2 of 2 plans' in detail
    assert 'command journal contains entries for 1 of 2 plans' in detail
    assert mirror_history.detail(conn, pub, summary) == detail and len(classify_calls) == 1
    assert len(row_reads) == 2, 'warm read restored historical pending snapshots'
    assert before == conn.execute('SELECT payload,hmac_sha256 FROM sentinel_paper_mirror_dependencies ORDER BY plan_id').fetchall()
    conn.rollback()
    journal.save_command(conn, cmd(BBB, plan=plans[1].plan_id))
    conn.commit()
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    assert 'entries for 2 of 2 plans' in mirror_history.detail(conn, pub, summary)
    assert len(classify_calls) == 1, 'fresh command presence reran the historical classifier'
    assert len(row_reads) == 2
    memo.slot[64] ^= 1
    assert 'latest check on 2 of 2 plans' in mirror_history.detail(conn, pub, summary)
    assert len(classify_calls) == 2, 'damaged signature reused'
    assert 'latest check on 2 of 2 plans' in mirror_history.detail(conn, pub,
        dict(summary, indexed_history_context='b'*64))
    assert len(classify_calls) == 3, 'changed mirror coverage reused'
    assert 'latest check on 2 of 2 plans' in mirror_history.detail(conn, pub, summary)
    assert len(classify_calls) == 4
    conn.rollback()
    changed = dict(before[0][0], material_sha256=digest({'DIFFERENT-MATERIAL':'2'}))
    mirror_projection._write(conn, changed)
    conn.commit()
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    mixed = mirror_history.detail(conn, pub, summary)
    assert 'latest check on 1 of 2 plans' in mixed and 'without a dividend-only explanation total 1' in mixed
    assert len(classify_calls) == 5, 'changed plan material reused'


def _use_memo_in_observer(memo, subject, produce):
    if produce:
        memo.store(subject, 3)
    return memo.read(subject, 8)


def test_serial_spawned_workers_share_only_the_authenticated_count(monkeypatch):
    from sentinel import supervisor_io
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','mirror-memo-test-key-'*3)
    memo = mirror_history.ClassificationMemo()
    for produce in (True, False):
        assert supervisor_io.run(_use_memo_in_observer, memo, 'c'*64, produce, start_method='spawn', timeout=20) == 3
    assert memo.read('b'*64, 8) is None
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','changed-mirror-key-'*3)
    assert memo.read('c'*64, 8) is None


@pytest.mark.parametrize('change', ['another-material', 'same-id-structural', 'unknown-marker', 'duplicate', 'symbol-only'])
def test_incomplete_or_mixed_material_never_gets_a_dividend_only_explanation(witness, change):
    marker = witness['marker']
    row = row_for(witness)
    original = deepcopy(witness['old_day'])
    markers = [marker]
    proved = {classify(witness).proof.marker_sha256}
    if change == 'another-material':
        row['material_sha256'] = digest({SID: 'UNSUPPORTED:historycorrection:'+marker['source_row_id'], 'other': '2'})
    elif change == 'same-id-structural':
        original['unresolved'].append(dict(security_id=SID, ticker='DELL'))
    elif change == 'unknown-marker':
        proved.clear()
    elif change == 'duplicate':
        markers.append(dict(marker))
    else:
        markers.append(dict(marker, security_id=None, action='merger'))
    assert not mirror_history._cash_only(row, original, markers, proved), 'mixed historical check was called dividend-only'


def test_removing_whole_material_commitment_fails_the_mixed_witness(monkeypatch, witness):
    source = inspect.getsource(mirror_history._cash_only)
    guard = "digest(material) == row['material_sha256']"
    assert source.count(guard) == 1
    namespace = dict(vars(mirror_history))
    exec(compile(source.replace(guard, 'True'), '<mirror-material-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(mirror_history, '_cash_only', namespace['_cash_only'])
    with pytest.raises(AssertionError, match='mixed historical check was called dividend-only'):
        test_incomplete_or_mixed_material_never_gets_a_dividend_only_explanation(witness, 'another-material')


def test_missing_or_large_history_keeps_generic_warning_without_qualification():
    assert 'historical informational mirror mismatch' in mirror_history.detail(None, None, {'historical_mismatch_count': 1})
    assert 'historical informational mirror mismatch' in mirror_history.detail(None, None,
        {'historical_mismatch_count': 9, 'indexed_history_publication': 23})
