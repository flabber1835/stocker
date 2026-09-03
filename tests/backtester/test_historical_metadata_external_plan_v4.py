from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

from backtester.plan_historical_metadata_external_v4 import build_plan, issuer_state


def _write(path: Path) -> None:
    fields = [
        "security_id","ticker","first_session","last_session","bucket",
        "type_unresolved","type_first","sector_unresolved","sector_first",
        "issuer_resolved","issuer_unresolved",
    ]
    rows = [
        {"security_id":"1","ticker":"AAA","first_session":"2006-01-03","last_session":"2008-01-01","bucket":"SECTOR_ONLY","type_unresolved":"0","type_first":"","sector_unresolved":"100","sector_first":"2006-01-03","issuer_resolved":"100","issuer_unresolved":"0"},
        {"security_id":"2","ticker":"BBB","first_session":"2010-01-04","last_session":"2012-01-01","bucket":"TYPE_AND_SECTOR","type_unresolved":"80","type_first":"2010-02-01","sector_unresolved":"90","sector_first":"2010-01-04","issuer_resolved":"20","issuer_unresolved":"70"},
        {"security_id":"3","ticker":"CCC","first_session":"2020-01-02","last_session":"2021-01-01","bucket":"TYPE_ONLY","type_unresolved":"60","type_first":"2020-01-02","sector_unresolved":"0","sector_first":"","issuer_resolved":"0","issuer_unresolved":"60"},
        {"security_id":"4","ticker":"DDD","first_session":"2015-01-02","last_session":"2016-01-01","bucket":"SECTOR_ONLY","type_unresolved":"0","type_first":"","sector_unresolved":"50","sector_first":"2015-01-02","issuer_resolved":"50","issuer_unresolved":"0"},
    ]
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer=csv.DictWriter(text,fieldnames=fields,lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def _read(path: Path):
    with gzip.open(path,"rt",encoding="utf-8",newline="") as fh:
        return list(csv.DictReader(fh))


def test_identity_state_contract():
    assert issuer_state({"issuer_resolved":"10","issuer_unresolved":"0"}) == "FULL_CAUSAL_IDENTITY"
    assert issuer_state({"issuer_resolved":"10","issuer_unresolved":"2"}) == "PARTIAL_CAUSAL_IDENTITY"
    assert issuer_state({"issuer_resolved":"0","issuer_unresolved":"2"}) == "NO_CAUSAL_IDENTITY"


def test_known_partial_scope_and_strict_prior(tmp_path: Path):
    inventory=tmp_path/"u.csv.gz"
    _write(inventory)
    output=tmp_path/"out"
    summary=build_plan(inventory,output,identity_scope="known-or-partial")
    rows={row["ticker"]:row for row in _read(output/"plan.csv.gz")}
    assert summary["cohort_rows"] == 3
    assert set(rows)=={"AAA","BBB","DDD"}
    assert rows["AAA"]["search_end"] == "2006-01-02"
    assert rows["BBB"]["authority_before"] == "2010-01-04"
    assert rows["BBB"]["search_end"] == "2010-01-03"
    assert rows["AAA"]["source_inventory_sha256"] == summary["source_inventory_sha256"]
    assert (output/"SHA256SUMS.txt").is_file()


def test_shards_are_disjoint_and_cover_cohort(tmp_path: Path):
    inventory=tmp_path/"u.csv.gz"
    _write(inventory)
    seen=set()
    for index in range(2):
        output=tmp_path/f"s{index}"
        build_plan(inventory,output,identity_scope="known-or-partial",shard_index=index,shard_count=2)
        ids={row["security_id"] for row in _read(output/"plan.csv.gz")}
        assert not (seen & ids)
        seen |= ids
    assert seen == {"1","2","4"}
