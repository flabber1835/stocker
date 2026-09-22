from research.owned55_replay.continue_run import segment_directories


def test_restart_selects_segment_directory_not_log(tmp_path):
    first, last = (tmp_path/name for name in ("segment-001", "segment-002"))
    first.mkdir()
    last.mkdir()
    (tmp_path/"segment-002.log").write_text("completed")
    assert segment_directories(tmp_path) == [first, last]
