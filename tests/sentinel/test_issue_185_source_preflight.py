import pytest

from sentinel.feed import archive_tables, ingest


def test_absent_replay_capture_fails_before_creating_a_durable_run():
    with pytest.raises(archive_tables.CaptureRequired):
        ingest._validate_source_before_run(archive_tables.fetch_table)


def test_injected_table_source_has_no_remote_preflight():
    ingest._validate_source_before_run(lambda table, params=None: ())
