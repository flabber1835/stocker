from __future__ import annotations

import csv
import gzip
import math
from collections import defaultdict


def rows(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_ipos_do_not_exist_before_listing(adversarial_world):
    world, _, _ = adversarial_world
    master = rows(world / "public/security_master.csv.gz")
    prices = rows(world / "public/prices.csv.gz")
    listing = {}
    for row in master:
        listing[row["company_id"]] = min(listing.get(row["company_id"], row["listing_date"]), row["listing_date"])
    assert all(row["date"] >= listing[row["company_id"]] for row in prices)


def test_delisted_and_bankrupt_companies_remain_in_history(adversarial_world):
    world, _, _ = adversarial_world
    master = rows(world / "public/security_master.csv.gz")
    prices = rows(world / "public/prices.csv.gz")
    actions = rows(world / "public/actions.csv.gz")
    historical = {row["company_id"] for row in prices}
    delisted = {row["company_id"] for row in master if row["delist_date"]}
    bankrupt = {row["company_id"] for row in actions if row["action_type"] == "bankruptcy" and row["post_mechanical_price"]}
    assert delisted and bankrupt
    assert delisted <= historical
    assert bankrupt <= historical


def test_no_survivorship_filter(adversarial_world):
    world, _, _ = adversarial_world
    master = rows(world / "public/security_master.csv.gz")
    prices = rows(world / "public/prices.csv.gz")
    universe = rows(world / "public/universe.csv.gz")
    listed = {row["company_id"] for row in master}
    assert {row["company_id"] for row in prices} == listed
    assert {row["company_id"] for row in universe} == listed


def test_delisted_security_has_no_price_on_or_after_delist(adversarial_world):
    world, _, _ = adversarial_world
    master = rows(world / "public/security_master.csv.gz")
    prices = rows(world / "public/prices.csv.gz")
    max_price = {}
    for row in prices:
        max_price[row["company_id"]] = max(max_price.get(row["company_id"], row["date"]), row["date"])
    for row in master:
        if row["delist_date"]:
            assert max_price[row["company_id"]] < row["delist_date"]


def test_splits_and_reverse_splits_preserve_mechanical_market_value(adversarial_world):
    world, _, _ = adversarial_world
    actions = rows(world / "public/actions.csv.gz")
    split_rows = [r for r in actions if r["action_type"] in {"split", "reverse_split"} and r["post_mechanical_price"]]
    assert split_rows
    for row in split_rows:
        pre_p = float(row["pre_price"]); post_p = float(row["post_mechanical_price"])
        pre_s = float(row["pre_shares"]); post_s = float(row["post_shares"]); ratio = float(row["ratio"])
        assert math.isclose(post_s, pre_s * ratio, rel_tol=2e-10, abs_tol=1e-6)
        assert math.isclose(post_p * post_s, pre_p * pre_s, rel_tol=2e-9, abs_tol=1e-3)


def test_dividends_reduce_cash_and_ex_dividend_raw_price(adversarial_world):
    world, _, _ = adversarial_world
    actions = rows(world / "public/actions.csv.gz")
    dividends = [r for r in actions if r["action_type"] == "dividend" and r["post_mechanical_price"] and float(r["cash_amount"] or 0) > 0]
    assert dividends
    for row in dividends:
        assert float(row["post_mechanical_price"]) <= float(row["pre_price"]) + 1e-9
        assert float(row["post_cash"]) <= float(row["pre_cash"]) + 1e-5


def test_ticker_and_identifier_changes_preserve_company_identity(adversarial_world):
    world, _, _ = adversarial_world
    master = rows(world / "public/security_master.csv.gz")
    intervals = defaultdict(list)
    for row in master:
        intervals[row["company_id"]].append(row)
    changed = [seq for seq in intervals.values() if len(seq) > 1]
    assert changed
    for seq in changed:
        seq.sort(key=lambda r: r["valid_from"])
        for left, right in zip(seq, seq[1:]):
            assert left["company_id"] == right["company_id"]
            assert left["valid_to"] < right["valid_from"]
