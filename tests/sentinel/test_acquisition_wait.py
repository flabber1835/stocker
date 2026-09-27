"""Foreground waiting policy, independent of provider bytes and economics."""
from unittest.mock import Mock

import pytest

from sentinel.feed import preparation_wait as driver, rolling_jobs as jobs, sharadar


def setup(monkeypatch, **updates):
    state = dict(state="WAIT_SOURCE", owner=None, retry_seconds=25.,
                 remaining_seconds=100., reason="EXPORT_GENERATION_PENDING")
    state.update(updates)
    conn = Mock()
    def status(*args):
        conn.in_transaction = True
        return dict(state)
    def rollback():
        conn.in_transaction = False
    conn.rollback.side_effect = rollback
    monkeypatch.setattr(jobs, "status", status)
    return conn, state


def test_wait_respects_retry_time_and_reuses_exact_job(monkeypatch, capsys):
    conn, state = setup(monkeypatch)
    prepare = Mock(side_effect=[sharadar.SharadarRetryDeferred(25), {"published": True}])
    sleeps = []
    def sleep(seconds):
        assert conn.in_transaction is False
        sleeps.append(seconds)
        state["retry_seconds"] -= seconds
        state["remaining_seconds"] -= seconds
    result = driver.run(conn, "same-job", prepare=prepare, check_target=lambda: None, sleep=sleep)
    assert result == {"published": True}
    assert sleeps == [10, 10, 5]
    assert [call.args for call in prepare.call_args_list] == [(conn, "same-job")] * 2
    from scripts.sentinel_go_feed_progress import collect
    assert len(collect(capsys.readouterr().err)) == 3


def test_deadline_expires_without_retrying_or_renewing(monkeypatch):
    conn, state = setup(monkeypatch, remaining_seconds=4.)
    expire = Mock()
    monkeypatch.setattr(jobs, "expire", expire)
    prepare = Mock(side_effect=sharadar.SharadarRetryDeferred(25))
    def sleep(seconds):
        assert seconds == 4
        state["remaining_seconds"] = 0
    with pytest.raises(jobs.JobRefused, match="deadline"):
        driver.run(conn, "job", prepare=prepare, check_target=lambda: None, sleep=sleep)
    assert prepare.call_count == 1
    expire.assert_called_once_with(conn, "job")


@pytest.mark.parametrize("error", [ValueError("integrity"), KeyboardInterrupt(),
                                  sharadar.SharadarRetryDeferred(30)])
def test_unrecorded_or_unrecognized_failure_is_not_retried(monkeypatch, error):
    conn, _ = setup(monkeypatch, state="ACQUIRING")
    prepare = Mock(side_effect=error)
    sleep = Mock()
    with pytest.raises(type(error)):
        driver.run(conn, "job", prepare=prepare, check_target=lambda: None, sleep=sleep)
    sleep.assert_not_called()
    assert prepare.call_count == 1


def test_source_final_change_stops_before_next_attempt(monkeypatch):
    conn, _ = setup(monkeypatch)
    prepare = Mock(side_effect=sharadar.SharadarRetryDeferred(30))
    check = Mock(side_effect=[None, ValueError("target changed")])
    with pytest.raises(ValueError, match="target changed"):
        driver.run(conn, "job", prepare=prepare, check_target=check, sleep=Mock())
    assert prepare.call_count == 1


def test_integrity_failure_is_not_retried_even_if_job_was_waiting(monkeypatch):
    conn, _ = setup(monkeypatch)
    prepare = Mock(side_effect=ValueError("integrity"))
    with pytest.raises(ValueError, match="integrity"):
        driver.run(conn, "job", prepare=prepare, check_target=lambda: None,
                   sleep=lambda _: pytest.fail("integrity must not wait"))


def test_competing_worker_publication_is_read_without_new_job(monkeypatch):
    conn, state = setup(monkeypatch, state="ACQUIRING", owner="other")
    prepare = Mock(side_effect=[jobs.JobWaiting("owned"), {"receipt": "existing"}])
    def sleep(_):
        state.update(state="PUBLISHED", owner=None, retry_seconds=0, remaining_seconds=0)
    assert driver.run(conn, "job", prepare=prepare, check_target=lambda: None,
                      sleep=sleep) == {"receipt": "existing"}
    assert prepare.call_count == 2


def test_publication_racing_with_busy_claim_returns_existing_receipt(monkeypatch):
    conn, _ = setup(monkeypatch, state="PUBLISHED", remaining_seconds=0.)
    prepare = Mock(side_effect=[jobs.JobWaiting("owned"), {"receipt": "existing"}])
    sleep = Mock()
    assert driver.run(conn, "job", prepare=prepare, check_target=lambda: None,
                      sleep=sleep) == {"receipt": "existing"}
    sleep.assert_not_called()


def test_operator_interrupt_during_wait_exits_immediately(monkeypatch):
    conn, _ = setup(monkeypatch)
    prepare = Mock(side_effect=sharadar.SharadarRetryDeferred(30))
    with pytest.raises(KeyboardInterrupt):
        driver.run(conn, "job", prepare=prepare, check_target=lambda: None,
                   sleep=Mock(side_effect=KeyboardInterrupt))
    assert prepare.call_count == 1
