from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backtester.sp500_pit_corpus import (
    Interval,
    apply_overlay,
    git_blob_sha1,
    load_base_intervals,
    load_overlay,
    membership_on,
)


def _write_source(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "source.csv"
    path.write_text(text, encoding="utf-8")
    return path


def _write_overlay(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "overlay.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_end_date_is_first_absent_date(tmp_path):
    source = _write_source(
        tmp_path,
        "ticker,start_date,end_date\nAAA,1996-01-02,1998-01-01\nBBB,1996-01-02,\n",
    )
    intervals = load_base_intervals(source, "1996-01-02", "2000-01-01")
    assert membership_on(intervals, "1997-12-31") == ("AAA", "BBB")
    assert membership_on(intervals, "1998-01-01") == ("BBB",)


def test_reentry_is_preserved(tmp_path):
    source = _write_source(
        tmp_path,
        "ticker,start_date,end_date\nAAA,1996-01-02,1998-01-01\nAAA,2002-01-02,2003-01-02\n",
    )
    intervals = load_base_intervals(source, "1996-01-02", "2006-01-03")
    assert len(intervals) == 2
    assert membership_on(intervals, "1999-01-01") == ()
    assert membership_on(intervals, "2002-01-02") == ("AAA",)


def test_official_overlay_closes_old_and_opens_new(tmp_path):
    base = [
        Interval("OLD", "2000-01-01", None, "secondary_historical", "secondary"),
        Interval("KEEP", "2000-01-01", None, "secondary_historical", "secondary"),
    ]
    overlay_path = _write_overlay(
        tmp_path,
        "effective_date,action,ticker,announced_date,authority_url,authority\n"
        "2026-08-05,delete,OLD,2026-07-31,https://example.test/change,S&P Dow Jones Indices\n"
        "2026-08-05,add,NEW,2026-07-31,https://example.test/change,S&P Dow Jones Indices\n",
    )
    overlay = load_overlay(overlay_path, start="1996-01-02", end="2026-09-03")
    result = apply_overlay(base, overlay)
    assert membership_on(result, "2026-08-04") == ("KEEP", "OLD")
    assert membership_on(result, "2026-08-05") == ("KEEP", "NEW")
    old = next(i for i in result if i.ticker == "OLD")
    new = next(i for i in result if i.ticker == "NEW")
    assert old.member_until_exclusive == "2026-08-05"
    assert old.end_authority.startswith("official:S&P Dow Jones Indices:")
    assert new.confidence == "official_primary"


def test_overlay_must_be_announced_strict_prior(tmp_path):
    overlay_path = _write_overlay(
        tmp_path,
        "effective_date,action,ticker,announced_date,authority_url,authority\n"
        "2026-08-05,delete,OLD,2026-08-05,https://example.test/change,S&P Dow Jones Indices\n"
        "2026-08-05,add,NEW,2026-08-05,https://example.test/change,S&P Dow Jones Indices\n",
    )
    with pytest.raises(RuntimeError, match="strict-prior"):
        load_overlay(overlay_path, start="1996-01-02", end="2026-09-03")


def test_overlay_must_be_balanced(tmp_path):
    overlay_path = _write_overlay(
        tmp_path,
        "effective_date,action,ticker,announced_date,authority_url,authority\n"
        "2026-08-05,add,NEW,2026-07-31,https://example.test/change,S&P Dow Jones Indices\n",
    )
    with pytest.raises(RuntimeError, match="unbalanced"):
        load_overlay(overlay_path, start="1996-01-02", end="2026-09-03")


def test_overlapping_intervals_fail(tmp_path):
    source = _write_source(
        tmp_path,
        "ticker,start_date,end_date\nAAA,2000-01-01,2002-01-02\nAAA,2001-01-01,2003-01-01\n",
    )
    with pytest.raises(RuntimeError, match="overlapping"):
        load_base_intervals(source, "1996-01-02", "2006-01-03")


def test_git_blob_sha_matches_git_object_formula(tmp_path):
    path = tmp_path / "x"
    path.write_bytes(b"abc\n")
    expected = hashlib.sha1(b"blob 4\0abc\n").hexdigest()
    assert git_blob_sha1(path) == expected
