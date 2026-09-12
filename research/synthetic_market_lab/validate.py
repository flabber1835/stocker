from __future__ import annotations

import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .io import file_record, sha256_file, write_canonical_json


def _iter_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _float(value: str) -> float:
    return float(value) if value else math.nan


def validate_world(world_dir: str | Path, *, write_report: bool = True) -> dict[str, object]:
    world = Path(world_dir)
    public = world / "public"
    truth = world / "ground_truth"
    manifest = json.loads((world / "manifest.json").read_text(encoding="utf-8"))
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, condition: bool, detail: object) -> None:
        checks[name] = {"passed": bool(condition), "detail": detail}

    # Hash integrity for all generator artifacts recorded before validation.json exists.
    mismatches = []
    for rel, recorded in manifest["files"].items():
        p = world / rel
        if not p.is_file() or sha256_file(p) != recorded["sha256"] or p.stat().st_size != recorded["bytes"]:
            mismatches.append(rel)
    check("manifest_file_hashes", not mismatches, {"mismatches": mismatches})

    causal = json.loads((truth / "causal_dependencies.json").read_text(encoding="utf-8"))
    positive = {name: rule.get("max_future_lag") for name, rule in causal["rules"].items() if rule.get("max_future_lag", 0) > 0}
    check("no_future_causal_dependencies", not positive, {"positive_future_lags": positive})
    check("adapter_ground_truth_forbidden", causal["rules"]["adapter"].get("ground_truth_access") is False, causal["rules"]["adapter"])

    security_rows = list(_iter_rows(public / "security_master.csv.gz"))
    by_security: dict[str, list[dict[str, str]]] = defaultdict(list)
    listed_companies: set[str] = set()
    delisted_companies: set[str] = set()
    bankruptcy_companies: set[str] = set()
    action_causality_bad = 0
    for row in security_rows:
        by_security[row["security_id"]].append(row)
        listed_companies.add(row["company_id"])
        if row["delist_date"]:
            delisted_companies.add(row["company_id"])
    for row in _iter_rows(public / "actions.csv.gz"):
        if row["announced_at"] > row["effective_date"]:
            action_causality_bad += 1
        if row["action_type"] == "bankruptcy" and row["post_mechanical_price"]:
            bankruptcy_companies.add(row["company_id"])
    check("corporate_actions_are_causal", action_causality_bad == 0, {"violations": action_causality_bad})

    # Price chronology, active identity, OHLC and positive liquidity.
    price_min: dict[str, str] = {}
    price_max: dict[str, str] = {}
    price_rows = 0
    price_identity_bad = 0
    ohlc_bad = 0
    liquidity_bad = 0
    historical_companies: set[str] = set()
    for row in _iter_rows(public / "prices.csv.gz"):
        price_rows += 1
        historical_companies.add(row["company_id"])
        cid = row["company_id"]
        date = row["date"]
        price_min[cid] = min(price_min.get(cid, date), date)
        price_max[cid] = max(price_max.get(cid, date), date)
        candidates = [r for r in by_security.get(row["security_id"], []) if r["valid_from"] <= date and (not r["valid_to"] or date <= r["valid_to"])]
        if not candidates or all(r["ticker"] != row["ticker"] or r["company_id"] != cid for r in candidates):
            price_identity_bad += 1
        op, hi, lo, cl, adj = map(_float, (row["open"], row["high"], row["low"], row["close"], row["adj_close"]))
        if not (lo > 0 and lo <= min(op, cl) <= max(op, cl) <= hi and adj > 0):
            ohlc_bad += 1
        if _float(row["volume"]) < 0 or _float(row["dollar_volume"]) < 0 or _float(row["spread_bps"]) <= 0:
            liquidity_bad += 1
    check("price_identity_is_pit", price_identity_bad == 0, {"bad_rows": price_identity_bad, "rows": price_rows})
    check("price_ohlc_invariants", ohlc_bad == 0, {"bad_rows": ohlc_bad})
    check("liquidity_nonnegative", liquidity_bad == 0, {"bad_rows": liquidity_bad})

    ipo_bad = 0
    delist_bad = 0
    for row in security_rows:
        cid = row["company_id"]
        if cid in price_min and price_min[cid] < row["listing_date"] and row["valid_from"] == row["listing_date"]:
            ipo_bad += 1
        if row["delist_date"] and cid in price_max and price_max[cid] >= row["delist_date"]:
            # Delisting is effective at the start of the delist date; final tradable row is earlier.
            delist_bad += 1
    check("ipos_absent_before_listing", ipo_bad == 0, {"violations": ipo_bad})
    check("delistings_end_future_prices", delist_bad == 0, {"violations": delist_bad, "delisted_companies": len(delisted_companies)})
    check("dead_companies_retained_historically", delisted_companies <= historical_companies, {"delisted": len(delisted_companies), "historical": len(historical_companies)})
    check("bankrupt_companies_retained_historically", bankruptcy_companies <= historical_companies, {"bankrupt": len(bankruptcy_companies)})
    check("no_survivorship_filter", historical_companies == listed_companies, {"listed": len(listed_companies), "historical": len(historical_companies)})

    # Universe rows must have exactly one active public identity and cannot predate listings.
    universe_bad = 0
    universe_companies: set[str] = set()
    universe_rows = 0
    for row in _iter_rows(public / "universe.csv.gz"):
        universe_rows += 1
        universe_companies.add(row["company_id"])
        date = row["snapshot_date"]
        candidates = [r for r in by_security.get(row["security_id"], []) if r["valid_from"] <= date and (not r["valid_to"] or date <= r["valid_to"])]
        if not candidates or all(r["ticker"] != row["ticker"] or r["company_id"] != row["company_id"] for r in candidates):
            universe_bad += 1
    check("universe_membership_is_pit", universe_bad == 0, {"bad_rows": universe_bad, "rows": universe_rows})
    check("universe_retains_dead_history", delisted_companies <= universe_companies, {"delisted": len(delisted_companies), "universe_history": len(universe_companies)})

    # Disclosures: filing date is never before period end; revisions are later immutable rows; identities close.
    disclosure_bad = 0
    revision_bad = 0
    accounting_bad = 0
    versions: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    report_types: set[str] = set()
    period_ends: set[str] = set()
    disclosure_rows = 0
    for row in _iter_rows(public / "disclosures.csv.gz"):
        disclosure_rows += 1
        report_types.add(row["report_type"])
        period_ends.add(row["period_end"])
        if row["filed_at"] < row["period_end"]:
            disclosure_bad += 1
        versions[(row["company_id"], row["period_end"])].append((row["filed_at"], int(row["version"])))
        a, l, e = map(_float, (row["assets"], row["liabilities"], row["equity"]))
        if abs(a - (l + e)) > max(1e-5, max(abs(a), abs(l), abs(e)) * 2e-10):
            accounting_bad += 1
    for seq in versions.values():
        ordered = sorted(seq)
        if any(v2 <= v1 or d2 <= d1 for (d1, v1), (d2, v2) in zip(ordered, ordered[1:])):
            revision_bad += 1
    check("filing_dates_respected", disclosure_bad == 0, {"violations": disclosure_bad, "rows": disclosure_rows})
    check("revisions_are_forward_only", revision_bad == 0, {"periods_with_bad_versions": revision_bad, "restated_periods": sum(len(v) > 1 for v in versions.values())})
    check("reporting_calendars_and_annual_reports", {"quarterly", "annual"} <= report_types and len(period_ends) > 20, {"report_types": sorted(report_types), "distinct_period_ends": len(period_ends)})
    check("public_accounting_identities_close", accounting_bad == 0, {"violations": accounting_bad})

    truth_accounting_bad = 0
    truth_rows = 0
    for row in _iter_rows(truth / "company_quarterly.csv.gz"):
        truth_rows += 1
        a, l, e = map(_float, (row["true_assets"], row["true_liabilities"], row["true_equity"]))
        if abs(a - (l + e)) > max(1e-5, max(abs(a), abs(l), abs(e)) * 2e-10):
            truth_accounting_bad += 1
    check("true_accounting_identities_close", truth_accounting_bad == 0, {"violations": truth_accounting_bad, "rows": truth_rows})

    # Corporate action mechanical reconciliations recorded at effective processing.
    split_bad = dividend_bad = identity_change_bad = 0
    effective_counts: Counter[str] = Counter()
    for row in _iter_rows(public / "actions.csv.gz"):
        if not row["post_mechanical_price"]:
            continue
        typ = row["action_type"]
        effective_counts[typ] += 1
        pre_p = _float(row["pre_price"]); post_p = _float(row["post_mechanical_price"])
        pre_s = _float(row["pre_shares"]); post_s = _float(row["post_shares"])
        if typ in {"split", "reverse_split"}:
            ratio = _float(row["ratio"])
            if not (math.isclose(post_s, pre_s * ratio, rel_tol=2e-10, abs_tol=1e-6) and math.isclose(post_p * post_s, pre_p * pre_s, rel_tol=2e-9, abs_tol=1e-3)):
                split_bad += 1
        elif typ == "dividend":
            amount = _float(row["cash_amount"])
            if amount > 0 and not (post_p <= pre_p + 1e-9 and _float(row["post_cash"]) <= _float(row["pre_cash"]) + 1e-5):
                dividend_bad += 1
        elif typ in {"ticker_change", "identifier_change"}:
            if typ == "ticker_change" and not row["new_ticker"]:
                identity_change_bad += 1
            if typ == "identifier_change" and not row["new_security_id"]:
                identity_change_bad += 1
    check("splits_preserve_mechanical_value", split_bad == 0, {"violations": split_bad, "effective": effective_counts.get("split", 0) + effective_counts.get("reverse_split", 0)})
    check("dividends_reconcile_cash_and_price", dividend_bad == 0, {"violations": dividend_bad, "effective": effective_counts.get("dividend", 0)})
    check("identity_changes_have_successors", identity_change_bad == 0, {"violations": identity_change_bad, "ticker_changes": effective_counts.get("ticker_change", 0), "identifier_changes": effective_counts.get("identifier_change", 0)})

    # Strategy-visible files never contain latent/true fields.
    forbidden = {"regime", "health", "distress_probability", "latent_value", "true_revenue", "true_assets", "shock_id", "factor_premium"}
    contaminated: dict[str, list[str]] = {}
    for path in sorted(public.glob("*.csv.gz")):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            fields = set(next(csv.reader(handle)))
        overlap = sorted(fields & forbidden)
        if overlap:
            contaminated[path.name] = overlap
    check("ground_truth_isolated_from_public_schema", not contaminated, contaminated)

    passed = all(v["passed"] for v in checks.values())
    report = {
        "world_id": manifest["world_id"],
        "passed": passed,
        "checks": checks,
        "statistics": {
            "sessions": manifest["sessions"],
            "companies": manifest["companies"],
            "price_rows": price_rows,
            "universe_rows": universe_rows,
            "disclosure_rows": disclosure_rows,
            "ground_truth_quarter_rows": truth_rows,
            "listed_companies": len(listed_companies),
            "delisted_companies": len(delisted_companies),
            "bankrupt_companies": len(bankruptcy_companies),
            "effective_action_counts": dict(sorted(effective_counts.items())),
        },
    }
    if write_report:
        write_canonical_json(world / "validation.json", report)
    return report
