"""Actual signed review storage must not latch scheduled independent renewal."""
from dataclasses import replace
from sentinel.panel import model,review
from tests.sentinel.test_backup_renewal_projection import copying
from tests.sentinel.test_dashboard_review import conn,pg,clean,panel


def test_slow_daily_renewal_preserves_clean_signed_review_without_acknowledgement(conn):
    owner=review.Recorder();baseline=clean(owner,conn)
    values=copying();row=model.backup_restore_row(**values)
    initial=panel()
    page=replace(initial,now=values['now'],rows=[row if r.key=='backup_restore'
        else replace(r,as_of=values['now']) for r in initial.rows])
    progress=owner.observe(page,conn.info.dsn)
    assert progress.status=='CLEAN' and progress.head==baseline.head
    complete=owner.observe(panel(),conn.info.dsn)
    assert complete.status=='CLEAN' and complete.head==baseline.head
    failed=replace(page,rows=[replace(r,status=model.FAIL,recovery=None)
        if r.key=='backup_restore' else r for r in page.rows])
    assert owner.observe(failed,conn.info.dsn).status=='FAILED'
    assert owner.observe(panel(),conn.info.dsn).status=='REVIEW'
