"""Hosted, independent verification of the fixed-decision account pilot.

This module has no financial imports at module scope. Local tooling may inspect
its DATA/AST or exercise the refusal gate; account arithmetic is hosted only.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction
import gzip
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


ARMS = ("S", "A", "Q", "P")
START = "2018-01-02"
END = "2019-02-05"
COUNT = 275
FEE = Fraction(1, 1000)
P00_DAILY_SHA = "9f1c682846167a1deafe4496aa4d2e6b803f5650d9f2265b34c691bae56067b2"
P00_DAILY_BYTES = 170330724
BIL = "SENTINEL:BIL"
CHECKPOINT_SHA = "6942c696c752ee35d8a215a6ad138c71a69d9d8dd1337dcaa01519c3e141ea56"


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def hosted(args: argparse.Namespace) -> None:
    """Refuse before importing any strategy, projection or account module."""
    need(os.environ.get("PERSISTENT_RECONCILIATION_HOSTED") == "1", "HOSTED_ONLY")
    need(Path(__file__).resolve() == Path(
        "/current/research/persistent_share_reconciliation/review.py"),
        "EXACT_HOSTED_REVIEW_ENTRYPOINT")
    for name, expected in (("source", "/variant"), ("legacy", "/legacy"),
                           ("current", "/current"), ("p00", "/p00"),
                           ("input", "/input"), ("work", "/work/book"),
                           ("output", "/out/review")):
        need(getattr(args, name).resolve() == Path(expected), "EXACT_" + name.upper())
    forbidden = {
        "GH_TOKEN", "GITHUB_TOKEN", "CAPITAL_RISK_RESEARCH_KEY_20261027",
        "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_API_SECRET",
        "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "POLYGON_API_KEY",
        "SHARADAR_API_KEY", "DATABASE_URL", "PGPASSWORD",
    }
    need(not any(os.environ.get(key) for key in forbidden), "NO_FINANCIAL_CREDENTIALS")
    route = Path("/proc/net/route")
    need(route.is_file(), "LINUX_NETWORK_EVIDENCE")
    need(not any(line.split()[0] != "lo" for line in
                 route.read_text().splitlines()[1:] if line.split()), "NO_NETWORK_ROUTES")


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def json_value(value: object) -> object:
    """Use the journal's JSON representation without relaxing field values."""
    return json.loads(encoded(value))


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def number(value: object) -> Fraction:
    need(type(value) in (str, int, Decimal, Fraction), "EXACT_NUMBER_REQUIRED")
    return Fraction(value)


def equal_number(actual: object, expected: object, message: str) -> None:
    need(number(actual) == number(expected), message)


def read_json(path: Path) -> dict:
    need(path.is_file() and path.stat().st_size <= 64 * 1024**2, "BOUNDED_JSON")
    return json.loads(path.read_bytes())


def read_journal(path: Path) -> tuple[list[dict], dict]:
    need(path.is_file() and path.stat().st_size <= 512 * 1024**2, "BOUNDED_JOURNAL")
    rows, total, chain = [], 0, hashlib.sha256()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        for raw in stream:
            total += len(raw)
            need(total <= 512 * 1024**2 and len(raw) <= 16 * 1024**2,
                 "BOUNDED_JOURNAL_PLAINTEXT")
            need(raw.endswith(b"\n"), "NO_UNCOMMITTED_PARTIAL_LINE")
            chain.update(raw)
            rows.append(json.loads(raw))
    return rows, {"bytes": total, "records": len(rows),
                  "prefix_sha256": chain.hexdigest(), "file_sha256": file_sha(path)}


def check_snapshot(snapshot: dict) -> dict:
    need(set(snapshot) == {"state", "state_sha256"}, "EXACT_ACCOUNT_SNAPSHOT")
    need(digest(snapshot["state"]) == snapshot["state_sha256"], "ACCOUNT_SNAPSHOT_SHA")
    return snapshot["state"]


def account_nav(state: dict, marks: dict, *, claims: bool = True) -> Fraction:
    need(number(state["cash"]) >= 0, "NONNEGATIVE_CASH")
    value = number(state["cash"])
    for key, position in state["positions"].items():
        need(key == position["episode"] and number(position["shares"]) > 0,
             "POSITIVE_CAUSAL_POSITION")
        sid = position["security_id"]
        need(sid in marks and number(marks[sid]) > 0, "COMPLETE_RAW_MARKS")
        value += number(position["shares"]) * number(marks[sid])
    if claims:
        value += sum((number(c["amount"]) for c in state["claims"].values()), Fraction(0))
    return value


def source_rows(args: argparse.Namespace) -> tuple[list[dict], list[dict], dict]:
    book = args.p00 / "book"
    need(file_sha(book / "checkpoint.json.gz") == CHECKPOINT_SHA, "EXACT_P00_CHECKPOINT")
    with gzip.open(book / "checkpoint.json.gz", "rt") as stream:
        checkpoint = json.load(stream)
    rows, count, size, chain = [], 0, 0, hashlib.sha256()
    with (book / "daily.jsonl").open("rb") as stream:
        for raw in stream:
            need(raw.endswith(b"\n"), "SOURCE_COMPLETE_LINE")
            chain.update(raw)
            count += 1
            size += len(raw)
            if count <= COUNT:
                rows.append(json.loads(raw))
    need(size == P00_DAILY_BYTES and chain.hexdigest() == P00_DAILY_SHA,
         "ORIGINAL_FULL_DAILY_COMMITMENT")
    need(count == checkpoint["completed"] == 2156, "ORIGINAL_COMPLETE_SOURCE")
    committed = checkpoint["journals"]["daily"]
    need(committed["bytes"] == P00_DAILY_BYTES and
         committed["prefix_sha256"] == P00_DAILY_SHA, "CHECKPOINT_DAILY_AUTHORITY")
    need(rows[0]["session"] == START and rows[-1]["session"] == END and
         len({r["session"] for r in rows}) == COUNT, "EXACT_FIXED_PILOT_AXIS")
    return rows, checkpoint["run"]["state"]["ledger"]["events"], checkpoint


def validate_manifest(args: argparse.Namespace) -> dict:
    transfer = read_json(args.current / "research/persistent_share_reconciliation/input-transfer.json")
    manifest_path = args.input / "manifest.json"
    need(file_sha(manifest_path) == transfer["manifest_sha256"], "EXACT_STAGED_INPUT_MANIFEST")
    manifest = read_json(manifest_path)
    need(manifest["schema"] == "research.capital-risk-inputs/1" and
         manifest["purpose"] == "FIXED_ACCOUNT_RECONCILIATION_BIL" and
         manifest["legacy_commit"] == "0bc38753ac1f85b31eb95f560720e6b037e892c5",
         "INPUT_MANIFEST_SCOPE")
    need(manifest["protocol_sha256"] == file_sha(
        args.current / "docs/core-sentinel-reconciliation-20261109.md"), "INPUT_PROTOCOL_BINDING")
    actual = {p.relative_to(args.input).as_posix() for p in args.input.rglob("*") if p.is_file()}
    need(actual == set(manifest["members"]) | {"manifest.json"}, "EXACT_INPUT_MEMBER_SET")
    for name, spec in manifest["members"].items():
        path = args.input / name
        need(not path.is_symlink() and path.resolve().is_relative_to(args.input.resolve()),
             "CONFINED_INPUT_MEMBER")
        need(path.stat().st_size == spec["bytes"] and file_sha(path) == spec["sha256"],
             "INPUT_MEMBER_HASH:" + name)
    return manifest


class TextTokens(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tokens = []

    def handle_data(self, data):
        value = " ".join(data.split())
        if value:
            self.tokens.append(value)


def verify_bil(folder: Path, sessions: list[str]) -> tuple[dict, dict]:
    """Reconstruct normalized market facts from bound raw provider/issuer bytes."""
    data = read_json(folder / "bil-input.json")
    need(data["schema"] == "research.p00-bil-input/1" and data["qualified"] is True and
         data["qualification"]["status"] == "QUALIFIED_BIL_PRICE_AND_PAYABLE_TERMS" and
         data["unknown_terms"] == [], "COMPLETE_QUALIFIED_BIL_INPUT")
    need(data["pilot_sessions"] == sessions and
         sorted(data["daily"]) == ["2017-12-29"] + sessions, "BIL_EXACT_DATED_AXIS")
    source = folder / "sources"
    payloads = {}
    for name, spec in data["raw_payload_commitments"].items():
        path = source / name
        need(path.stat().st_size == spec["bytes"] and file_sha(path) == spec["sha256"],
             "BIL_RAW_PAYLOAD_BINDING")
        # These record commitments retain the provider's exact JSON numeric
        # lexical tokens as strings. The raw payload hash remains authority.
        payloads[name] = json.loads(path.read_bytes(), parse_float=str, parse_int=str)
    capture = source / "capture-manifest.json"
    need(file_sha(capture) == data["source_capture_sha256"], "BIL_CAPTURE_MANIFEST_BINDING")
    receipts = read_json(capture)["receipts"]
    bar_count = 0
    for domain in ("raw", "split", "all"):
        matched = [r for r in receipts if r["params"].get("adjustment") == domain]
        need(len(matched) == 1 and matched[0]["http_status"] == 200 and
             matched[0]["params"]["feed"] == "sip", "EXACT_BIL_BAR_REQUEST")
        raw = payloads[matched[0]["file"]]
        need(raw.get("next_page_token") is None, "COMPLETE_BIL_BAR_PAGE")
        bars = raw["bars"]["BIL"]
        need(len(bars) == len(sessions) + 1, "BIL_RAW_BAR_COUNT")
        by_day = {b["t"][:10]: b for b in bars}
        need(set(by_day) == set(data["daily"]), "BIL_RAW_BAR_AXIS")
        for day, normalized in data["daily"].items():
            original = by_day[day]
            evidence = normalized[domain + "_source"]
            need(evidence["source_bar_sha256"] == digest(original) and
                 evidence["source_payload_sha256"] == matched[0]["sha256"] and
                 evidence["timestamp"] == original["t"], "BIL_BAR_SOURCE_IDENTITY")
            for name, field in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c")):
                equal_number(normalized[domain + "_" + name], str(original[field]),
                             "BIL_ORIGINAL_" + domain.upper() + "_" + name.upper())
                need(number(normalized[domain + "_" + name]) > 0, "POSITIVE_BIL_PRICE")
            bar_count += 1
    actions_receipt = [r for r in receipts if "corporate-actions" in r["endpoint"]]
    need(len(actions_receipt) == 1, "BIL_ACTION_QUERY")
    response = payloads[actions_receipt[0]["file"]]
    need(response.get("next_page_token") is None, "COMPLETE_BIL_ACTION_PAGE")
    actions_raw = response.get("corporate_actions", response)
    dividends = actions_raw["cash_dividends"]
    providers = {str(r["id"]): r for r in dividends if START <= r["ex_date"] <= END}
    need(len(providers) == len(data["actions"]) == 13, "THIRTEEN_BIL_DIVIDENDS")
    workbook_path = source / "issuer-historical-distributions.xlsx"
    need(file_sha(workbook_path) == data["issuer_workbook_sha256"], "ISSUER_WORKBOOK_BYTES")
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(workbook_path) as archive:
        shared_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.findall(".//s:t", namespace))
                  for si in shared_xml.findall("s:si", namespace)]
        sheets = {}
        for action in data["actions"]:
            meta = action["issuer_source"]
            part = meta["worksheet_part"]
            if part not in sheets:
                content = archive.read(part)
                need(hashlib.sha256(content).hexdigest() == meta["worksheet_part_sha256"],
                     "ISSUER_WORKSHEET_BYTES")
                cells = {}
                for cell in ET.fromstring(content).findall(".//s:c", namespace):
                    value = cell.find("s:v", namespace)
                    text = "" if value is None else (value.text or "")
                    if cell.get("t") == "s" and text:
                        text = shared[int(text)]
                    cells[cell.attrib["r"]] = text
                sheets[part] = cells
            source_cells = sheets[part]
            for coordinate, expected in meta["cells"].items():
                need(source_cells.get(coordinate, "") == expected["value"], "ISSUER_ORIGINAL_CELL")
            row = str(meta["row"])
            need(source_cells["B" + row] == "BIL" and source_cells["C" + row] == "78468R663",
                 "ISSUER_SYMBOL_CUSIP")
            from datetime import datetime
            for column, key in (("D", "ex_date"), ("E", "record_date"), ("F", "payable_date")):
                value = datetime.strptime(source_cells[column + row], "%m/%d/%Y").date().isoformat()
                need(value == action[key], "ISSUER_DISTRIBUTION_DATE")
            equal_number(source_cells["G" + row], action["rate"], "ISSUER_EXACT_CASH_RATE")
            original = providers[action["id"]]
            need(digest(original) == action["source_record_sha256"] and
                 action["source_payload_sha256"] == actions_receipt[0]["sha256"],
                 "ORIGINAL_PROVIDER_ACTION_BINDING")
            need(action["ex_date"] == original["ex_date"] and
                 action["symbol"] == "BIL" and action["security_id"] == BIL and
                 action["currency"] == "USD" and action["foreign"] is False,
                 "NORMALIZED_BIL_IDENTITY_AND_CURRENCY")
            equal_number(action["rate"], str(original["rate"]), "PROVIDER_EXACT_CASH_RATE")
            need(action["ex_date"] <= action["record_date"] <= action["payable_date"],
                 "DISTRIBUTION_ECONOMIC_DATES")
    html_path = source / "issuer-bil-identity.html"
    need(file_sha(html_path) == data["issuer_identity_html_sha256"], "ISSUER_CURRENCY_HTML")
    parser = TextTokens()
    parser.feed(html_path.read_text(encoding="utf-8"))
    text = " ".join(parser.tokens)
    need("78468R663" in text and "US78468R6633" in text and "BIL" in text,
         "ISSUER_CURRENCY_IDENTITY")
    need(any(parser.tokens[i:i + 2] == ["Base Currency", "USD"]
             for i in range(len(parser.tokens) - 1)), "ISSUER_EXPLICIT_USD_BASE_CURRENCY")
    return data, {"bars_reconstructed": bar_count, "distribution_crossmatches": 13,
                  "provider_issuer_terms_verified": True, "raw_bil_input_sha256": file_sha(folder / "bil-input.json")}


def replay_event(previous: dict, item: dict, prices: dict) -> dict:
    """Derive each ledger state without invoking producer account operations."""
    record, context = item["record"], item.get("context", {})
    event = record["event"]
    operation, day = event["operation"], event["session"]
    need(START < day <= END, "EVENT_WITHIN_FUNDED_PILOT")
    need(previous["last_session"] is None or previous["last_session"] <= day,
         "EVENT_CURSOR")
    need(event["event_id"] not in previous["applied_events"], "EVENT_EXACTLY_ONCE")
    equal_number(record["cash_before"], previous["cash"], "EVENT_CASH_PREDECESSOR")
    expected = deepcopy(previous)
    cash = number(previous["cash"])
    positions, claims = expected["positions"], expected["claims"]
    retired = list(expected["retired"])

    if operation in ("BUY", "SELL"):
        intent = context["intent"]
        for key, source_key in (("episode", "episode"), ("security_id", "security_id"),
                                ("side", "operation")):
            need(intent[key] == event[source_key], "TRADE_INTENT_IDENTITY")
        need(intent["signal_session"] < intent["execution_session"] == day,
             "NEXT_OPEN_NOT_SAME_CLOSE")
        key, sid = event["episode"], event["security_id"]
        need(key not in retired, "NO_RETIRED_EPISODE_REENTRY")
        price = number(prices[sid]["raw_open"])
        need(price > 0, "RAW_OPEN_POSITIVE")
        equal_number(event["raw_price"], price, "BOUND_RAW_OPEN_FILL")
        requested = number(intent["shares"])
        equal_number(event["requested_shares"], requested, "REQUESTED_TARGET_DELTA")
        need(requested > 0, "POSITIVE_TRADE_REQUEST")
        before = number(positions[key]["shares"]) if key in positions else Fraction(0)
        if key in positions:
            need(positions[key]["security_id"] == sid and
                 positions[key]["kind"] == intent["kind"], "TRADE_POSITION_IDENTITY")
        if operation == "BUY":
            need(requested.denominator == 1 and intent["source_episode_live"] and
                 intent["kind"] != "ACTION_CHILD", "WHOLE_LIVE_BUY")
            filled = min(requested, Fraction(cash // (price * (1 + FEE))))
            cash -= filled * price * (1 + FEE)
            after = before + filled
            if filled:
                positions[key] = {"episode": key, "security_id": sid,
                                  "ticker": intent["ticker"], "kind": intent["kind"],
                                  "shares": str(after)}
        else:
            need(key in positions and requested <= before, "NO_OVERSELL")
            filled, after = requested, before - requested
            cash += filled * price * (1 - FEE)
            if after:
                positions[key]["shares"] = str(after)
            else:
                positions.pop(key)
        equal_number(event["filled_shares"], filled, "FEE_INCLUSIVE_CASH_CLIP")
        equal_number(event["fees"], filled * price * FEE, "ACTUAL_NOTIONAL_FEE")
        need(event["outcome"] == ("FILLED" if filled else "CASH_CLIPPED_ZERO"),
             "ACTUAL_FILL_OUTCOME")
        if intent["core_exit"]:
            need(operation == "SELL" and key not in positions, "COMPLETE_CORE_EXIT")
            retired.append(key)
    elif operation == "SPLIT":
        sid, ratio = event["security_id"], number(event["ratio"])
        need(ratio > 0, "POSITIVE_ACTION_RATIO")
        found = False
        for position in positions.values():
            if position["security_id"] == sid:
                found = True
                position["shares"] = str(number(position["shares"]) * ratio)
        need(found, "SPLIT_ACTUAL_OWNERSHIP")
    elif operation == "DIVIDEND_ACCRUED":
        key, sid = event["claim_id"], event["security_id"]
        need(key not in claims, "NO_DUPLICATE_ACCRUAL")
        terms = context["dividend_terms"]
        need(terms["ex_date"] == day and terms["pay_date"] >= day and
             terms["security_id"] == sid, "BOUND_DIVIDEND_TERMS")
        quantity = sum((number(p["shares"]) for p in positions.values()
                        if p["security_id"] == sid), Fraction(0))
        need(quantity > 0, "HELD_BEFORE_EX_DATE_FILL")
        amount = quantity * number(terms["cash_per_share"])
        equal_number(event["entitled_shares"], quantity, "HOLDER_LEVEL_ENTITLEMENT")
        equal_number(event["amount"], amount, "DIVIDEND_CASH_AMOUNT")
        claims[key] = {"security_id": sid, "entitled_shares": str(quantity),
                       "cash_per_share": str(number(terms["cash_per_share"])),
                       "amount": str(amount), "ex_session": day,
                       "pay_session": terms["pay_date"]}
    elif operation == "DIVIDEND_PAID":
        key = event["claim_id"]
        need(key in claims and claims[key]["pay_session"] <= day,
             "KNOWN_NOT_EARLY_OR_DUPLICATE_PAYMENT")
        amount = number(claims.pop(key)["amount"])
        equal_number(event["amount"], amount, "PAID_ENTITLEMENT_AMOUNT")
        cash += amount
    elif operation == "CASH_MERGER":
        sid, rate = event["security_id"], number(event["cash_per_share"])
        held = {k: p for k, p in positions.items() if p["security_id"] == sid}
        need(held and rate >= 0, "HELD_CASH_MERGER")
        quantity = sum((number(p["shares"]) for p in held.values()), Fraction(0))
        equal_number(event["entitled_shares"], quantity, "MERGER_HOLDER_QUANTITY")
        equal_number(event["amount"], quantity * rate, "MERGER_HOLDER_CASH")
        cash += quantity * rate
        for key in held:
            positions.pop(key)
        retired.extend(held)
    elif operation == "CONVERSION":
        terms = event["terms"]
        need(digest(terms) == event["terms_sha256"], "EXACT_ACTION_TERMS_SHA")
        need(terms["predecessor_sha256"] == digest(previous), "ACTION_PREDECESSOR_SHA")
        sid, delivered = terms["security_id"], terms["delivered_security_id"]
        held = {k: p for k, p in sorted(positions.items())
                if p["security_id"] == sid and p["kind"] == "EQUITY"}
        need(held, "CONVERSION_ACTUAL_OWNERSHIP")
        quantity = sum((number(p["shares"]) for p in held.values()), Fraction(0))
        entitled = quantity * number(terms["ratio"])
        whole = entitled.numerator // entitled.denominator
        fraction = entitled - whole
        settled = fraction
        if terms["rounding"] == "NEAREST_HUNDREDTH_HALF_UP":
            units, remainder = divmod(fraction.numerator * 100, fraction.denominator)
            settled = Fraction(units + (2 * remainder >= fraction.denominator), 100)
        else:
            need(terms["rounding"] == "EXACT", "DECLARED_ACTION_ROUNDING")
        need(not fraction or terms["cil_price"] is not None, "KNOWN_CIL_PRICE")
        cash_leg = quantity * number(terms["cash_per_share"])
        cil = settled * number(terms["cil_price"] or "0")
        for field, value in (("entitled_shares", quantity), ("whole_delivered", whole),
                             ("exact_fraction", fraction), ("settlement_fraction", settled),
                             ("cash_leg", cash_leg), ("cash_in_lieu", cil)):
            equal_number(event[field], value, "CONVERSION_" + field.upper())
        lots = {}
        for key, position in held.items():
            qty = Fraction(whole) * number(position["shares"]) / quantity
            lots[key] = str(qty)
            if qty:
                positions[key] = {"episode": key, "security_id": delivered,
                                  "ticker": terms["delivered_ticker"],
                                  "kind": "EQUITY", "shares": str(qty)}
            else:
                positions.pop(key)
                retired.append(key)
        need(lots == event["delivered_lots"], "EXACT_CONVERTED_LOTS")
        cash += cash_leg + cil
    elif operation == "CORE_EXIT_RETIRED":
        key = event["episode"]
        need(key not in positions and key not in retired, "EMPTY_EPISODE_RETIREMENT")
        retired.append(key)
    else:
        raise ValueError("UNREGISTERED_ACCOUNT_OPERATION:" + operation)

    need(cash >= 0, "NO_OVERSPEND")
    expected.update(cash=str(cash), retired=retired,
                    applied_events=list(previous["applied_events"]) + [event["event_id"]],
                    last_session=day)
    expected.pop("chain_sha256")
    need(expected == record["state_without_chain"], "INDEPENDENT_EVENT_FULL_STATE")
    equal_number(record["cash_after"], cash, "EVENT_CASH_AFTER")
    expected_chain = digest({"previous": previous["chain_sha256"],
                             "record": {k: v for k, v in record.items()
                                        if k != "chain_sha256"}})
    need(record["chain_sha256"] == expected_chain, "INDEPENDENT_ACCOUNT_EVENT_CHAIN")
    return {**expected, "chain_sha256": expected_chain}


def number_map(actual: dict, expected: dict, message: str) -> None:
    need(set(actual) == set(expected), message + "_KEYS")
    for key in actual:
        equal_number(actual[key], expected[key], message + ":" + key)


def trace_state(row: dict) -> dict:
    close = row["evidence"]["research_entry_audit"]["closing_accounting"]
    return {"last_processed_session": row["session"],
            "wealth_core": {"episodes": deepcopy(close["wealth_core"]["episodes"])},
            "pending": deepcopy(close["pending"]), "last_decision": deepcopy(row["decision"])}


def plan_namespace(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        target_exposure=Decimal(raw["target_exposure"]),
        decision_session=date.fromisoformat(raw["decision_session"]),
        target_basket={s: Decimal(q) for s, q in raw["target_basket"].items()},
        opening_intents=tuple(SimpleNamespace(**item) for item in raw["opening_intents"]))


def projection_namespace(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        target_basket={s: Decimal(q) for s, q in raw["target_basket"].items()},
        through_session=date.fromisoformat(raw["through_session"]),
        action_multipliers={s: Decimal(q) for s, q in raw.get("action_multipliers", {}).items()},
        action_evidence=tuple(raw.get("action_evidence", [])),
        opening_sizing=raw.get("opening_sizing"))


def verify_projection(row: dict, arm: str, record: dict, prior: dict | None,
                      marks: dict, next_day: str | None, api: SimpleNamespace) -> None:
    audit, pending = record["projection_audit"], record["pending"]
    state = trace_state(row)
    need(audit["state"] == state, "EXACT_SOURCE_TRACE_DTO")
    kwargs = audit["project_kwargs"]
    need(kwargs["defensive_security"] == BIL, "EXPLICIT_BIL_SLEEVE")
    number_map(kwargs["marks"], marks, "SOURCE_CLOSE_PROJECTION_MARKS")
    equal_number(kwargs["exposure"], str(row["decision"]["target_core_exposure"]),
                 "UNCHANGED_SENTINEL_TARGET")
    equal_number(kwargs["defensive_weight"], 1 - number(kwargs["exposure"]),
                 "EXPLICIT_DEFENSIVE_WEIGHT_NOT_CASH_SWEEP")
    equal_number(kwargs["nav"], record["sizing_nav"], "CLAIMS_EXCLUDED_FROM_SIZING")
    equal_number(kwargs["weight_denominator"], row["economics"]["parent_core_close_equity"],
                 "CORE_NAV_WEIGHT_DENOMINATOR")
    shares, tickers, intents, identities = {}, {}, [], {}
    for episode in state["wealth_core"]["episodes"].values():
        sid = str(episode["security_id"])
        need(sid not in shares, "PILOT_UNIQUE_SOURCE_SECURITY")
        shares[sid] = number(str(episode["current_shares"]))
        tickers[sid] = episode["ticker"]
        identities[sid] = {"episode": episode["signal_date"] + "/" + str(episode["slot_id"]),
                           "ticker": episode["ticker"], "slot_id": episode["slot_id"]}
    for order in state["pending"]:
        sid = str(order["security_id"])
        if order["operation"] == "CLOSE_POSITION":
            shares[sid] = shares.get(sid, Fraction(0)) - number(str(order["shares"]))
        else:
            need(order["operation"] == "OPEN_SLOT_POSITION" and
                 number(str(order["shares"])) == 0 and order["intended_dollars"] is not None,
                 "ORIGINAL_DOLLAR_OPENING_INTENT")
            intents.append(api.OpeningIntent(sid, int(order["slot_id"]),
                                             Decimal(str(order["intended_dollars"]))))
            tickers[sid] = order["ticker"]
            identities[sid] = {"episode": order["signal_session"] + "/" + str(order["slot_id"]),
                               "ticker": order["ticker"], "slot_id": order["slot_id"]}
    need(all(q >= 0 for q in shares.values()), "NO_CORE_TARGET_OVERCLOSE")
    shares = {s: q for s, q in shares.items() if q > 0}
    number_map(audit["canonical_target"]["shares"], shares, "SOURCE_SHARE_TARGET")
    number_map(pending["canonical_target_shares"], shares, "PENDING_SOURCE_SHARE_TARGET")
    need(audit["canonical_target"]["tickers"] == tickers, "SOURCE_TARGET_TICKERS")
    need(pending["identities"] == identities, "SOURCE_CAUSAL_ACCOUNT_IDENTITIES")
    intents.sort(key=lambda item: item.slot_id)
    need(audit["canonical_target"]["opening_intents"] == [i.to_dict() for i in intents],
         "SOURCE_OPENING_INTENT_DTO")
    need(pending["opening_intents"] == [i.to_dict() for i in intents] and
         pending["retained_targets"] == audit["retained_targets"], "PENDING_INTENT_AND_RETENTION")
    equal_number(pending["target_exposure"], kwargs["exposure"], "PENDING_UNCHANGED_EXPOSURE")
    equal_number(pending["nav"], record["sizing_nav"], "PENDING_SIZING_NAV")
    equal_number(pending["core_nav"], kwargs["weight_denominator"], "PENDING_CORE_NAV")
    number_map(pending["closing_marks"], marks, "PENDING_BOUND_CLOSE_MARKS")
    weights = {s: q * number(marks[s]) for s, q in shares.items()}
    number_map(kwargs["shadow_weights"], weights, "MARKED_CORE_NOTIONALS")
    call = {**kwargs,
            "shadow_weights": {s: api.exact_decimal(q) for s, q in weights.items()},
            "marks": {s: Decimal(v) for s, v in marks.items()}}
    for key in ("exposure", "nav", "defensive_weight", "weight_denominator"):
        call[key] = Decimal(kwargs[key])
    raw = api.project(**call)
    need(raw.to_dict() == audit["raw_projection"], "ACTUAL_CANONICAL_RAW_PROJECTION")
    target = api.ShadowTarget(shares={s: api.exact_decimal(q) for s, q in shares.items()},
                              tickers=tickers, opening_intents=tuple(intents))
    retained = None
    if prior is None:
        need(audit["prior_state"] is None and audit["previous_plan"] is None and
             audit["predecessor_projection"] is None, "NO_INVENTED_ACCOUNT_PREDECESSOR")
        if arm == "P":
            retained = {}
    else:
        previous_plan = {"target_exposure": prior["pending"]["target_exposure"],
                         "decision_session": prior["pending"]["signal_session"],
                         "target_basket": prior["pending"]["desired_basket"],
                         "opening_intents": prior["pending"]["opening_intents"]}
        need(audit["prior_state"] == prior["projection_audit"]["state"] and
             audit["previous_plan"] == previous_plan, "EXACT_RETAINED_SOURCE_PREDECESSOR")
        predecessor = audit["predecessor_projection"]
        expected_predecessor = {"target_basket": record["execution"]["desired_basket"],
            "through_session": row["session"], "action_multipliers": {}, "action_evidence": [],
            "opening_sizing": None,
            "research_opening_sizing": {"mode": "TRACE_DTO_IDEALIZED_RAW_OPEN",
                                        "entries": record["execution"]["intended_entry_sizing"]}}
        need(predecessor == expected_predecessor,
             "CURRENT_OPEN_INTENT_NOT_ACTUAL_FILL_PREDECESSOR")
        if arm == "P":
            retained = api.carry_quantities(previous=plan_namespace(previous_plan),
                previous_state=SimpleNamespace(**audit["prior_state"]),
                projection=projection_namespace(predecessor), state=SimpleNamespace(**state),
                exposure=call["exposure"])
    if retained is None:
        need(audit["retained_targets"] is None, "Q_RETENTION_DISABLED")
    else:
        number_map(audit["retained_targets"], retained, "CANONICAL_RETAINED_INTENT")
    final = api.apply(raw, targets=retained, canonical_target=target, marks=call["marks"])
    need(final.to_dict() == audit["final_projection"], "ACTUAL_CANONICAL_FINAL_PROJECTION")
    wanted = {s: str(q) for s, q in api.desired_basket(final).items()}
    for intent in intents:
        wanted[intent.security_id] = "0"
    # Canonical ownership uses (slot, signal-session) tuples in memory. The
    # journal necessarily stores those exact tuples as JSON arrays.
    ownership = json_value(api.ownership(SimpleNamespace(**state)))
    for sid in ownership:
        wanted.setdefault(sid, "0")
    need(audit["ownership"] == ownership and pending["ownership"] == ownership,
         "CANONICAL_CAUSAL_OWNERSHIP")
    number_map(audit["desired_basket"], wanted, "AUDITED_CLOSE_DESIRED_BASKET")
    number_map(pending["desired_basket"], wanted, "PENDING_CLOSE_DESIRED_BASKET")
    need(pending["signal_session"] == row["session"] and
         pending["execution_session"] == next_day and pending["decision_sha256"] == digest(row["decision"]),
         "SOURCE_CLOSE_NEXT_OPEN_COMMITMENT")
    for key in ("state_sha256", "input_sha256", "chain_sha256"):
        need(pending["source_" + key] == row[key], "PENDING_SOURCE_IDENTITY")


def verify_a_metadata(economics: dict, bars: dict, day: str, previous_bar_day: str,
                      index: int, original: dict) -> None:
    prices = economics["strategy_prices"]
    with localcontext() as context:
        context.prec = 28
        adjusted_open = (Decimal(bars[day]["all_open"]) * Decimal(bars[day]["all_close"])
                         / Decimal(bars[day]["all_close"]))
    source_prices = {
        "bil_open_signal": bars[day]["all_open"],
        "bil_close_signal": bars[day]["all_close"],
        "bil_close_adjusted": bars[day]["all_close"],
        "bil_close_unadjusted": bars[day]["raw_close"],
        "bil_previous_close_adjusted": bars[previous_bar_day]["all_close"],
        "bil_open_adjusted": str(adjusted_open),
    }
    need(set(prices) == set(source_prices) | {"bil_previous_session"},
         "A_CANONICAL_SEVEN_FIELD_PRICE_SHAPE")
    for key, value in source_prices.items():
        equal_number(prices[key], value, "A_ONLY_QUALIFIED_BIL_BRIDGE")
        need(prices[key] == format(Decimal(value).normalize(), "f"),
             "A_CANONICAL_PRICE_TEXT")
    need(prices["bil_previous_session"] == previous_bar_day and
         economics["strategy_prices_sha256"] == digest(prices), "A_DATED_SOURCE_PRICE_HASH")
    for key, value in original["economics"].items():
        if key.startswith("parent_core_") or key in ("starting_cash", "last_session", "research_entry_mode",
                                                      "measurement_anchor_session", "formed_startup_marks"):
            need(economics[key] == value, "A_UNCHANGED_CORE_OR_ORIGIN_FIELD:" + key)
    for key, value in (("bil_open_adjusted", adjusted_open),
        ("bil_close_adjusted", bars[day]["all_close"]),
        ("bil_previous_close_adjusted_current_publication", bars[previous_bar_day]["all_close"])):
        equal_number(economics[key], value, "A_ALL_CLOSES_ADJUSTED_BIL_SOURCE")
    need(economics["bil_previous_session"] == previous_bar_day,
         "A_ALL_CLOSES_TOP_LEVEL_PREVIOUS_SESSION")
    with localcontext() as context:
        context.prec = 28
        intraday = Decimal(bars[day]["all_close"]) / adjusted_open - 1
        overnight = (None if index < 2 else
            adjusted_open / Decimal(bars[previous_bar_day]["all_close"]) - 1)
    equal_number(economics["bil_intraday_return"], intraday,
                 "A_DESCRIPTIVE_INTRADAY_SOURCE_NOT_EARNED_ANCHOR_RETURN")
    if overnight is None:
        need(economics["bil_overnight_return"] is None,
             "A_NO_UNFUNDED_PRE_EXECUTION_OVERNIGHT")
    else:
        equal_number(economics["bil_overnight_return"], overnight,
                     "A_DESCRIPTIVE_OVERNIGHT_SOURCE")
    if index == 0:
        need(economics["held_allocation"] is None and
             economics["initial_deployment"] is False, "A_ANCHOR_REMAINS_UNFUNDED")
        for key, value in (("previous_strategy_nav", 50000), ("strategy_nav", 50000),
            ("strategy_cumulative_return", 0), ("turnover", 0),
            ("transaction_cost_factor", 1), ("gross_factor", 1), ("net_factor", 1)):
            equal_number(economics[key], value, "A_ANCHOR_NO_EARNED_PNL_OR_TRADE")


def scalar_factor(prior: dict, row: dict, economics: dict, events: list[dict]) -> dict:
    """Separate equations from the canonical scalar producer operation."""
    d = Decimal
    with localcontext() as context:
        context.prec = 28
        new = d(prior["pending_allocation"])
        opening, closing = d(economics["parent_core_open_equity"]), d(economics["parent_core_close_equity"])
        bo, bc, bp = (d(economics[k]) for k in
                      ("bil_open_adjusted", "bil_close_adjusted", "bil_previous_close_adjusted_current_publication"))
        if prior["held_allocation"] is None:
            marks = economics.get("formed_startup_marks")
            if marks is not None:
                audit = row["evidence"]["research_entry_audit"]
                close, opened = audit["closing_accounting"], audit["opening_accounting"]
                notional = sum((d(str(ep["current_shares"])) * d(str(marks[ep["security_id"]]))
                                for ep in close["wealth_core"]["episodes"].values()), d(0))
                fees = sum((d(str(e["fees"])) for e in events[opened["ledger"]["event_count"]:
                    close["ledger"]["event_count"]] if e["event_type"] in ("BUY", "SELL")), d(0))
                gross = 1 + new * ((closing + fees) / opening - 1) + (1 - new) * (bc / bo - 1)
                turnover = new * notional / opening + (1 - new)
                net = gross - d(".001") * turnover
                cost = net / gross
            else:
                turnover = 1 - new
                gross = 1 + new * (closing / opening - 1) + (1 - new) * (bc / bo - 1)
                cost = 1 - d(".001") * turnover
                net = gross * cost
        else:
            old, previous_close = d(prior["held_allocation"]), d(prior["parent_core_close_equity"])
            turnover = abs(new - old)
            gross = (new * closing / previous_close + (1 - new) * bc / bp if new == old else
                     (old * opening / previous_close + (1 - old) * bo / bp) *
                     (new * closing / opening + (1 - new) * bc / bo))
            cost = 1 - d(".001") * turnover
            net = gross * cost
        return {"gross_factor": gross, "net_factor": net, "turnover": turnover,
                "transaction_cost_factor": cost}


def verify_open(row: dict, record: dict, prior: dict, events: list[dict],
                opens: dict, api: SimpleNamespace) -> None:
    plan, execution = prior["pending"], record["execution"]
    day = row["session"]
    need(execution["signal_session"] == plan["signal_session"] < day == plan["execution_session"],
         "NEXT_SOURCE_OPEN_EXECUTION")
    equal_number(execution["held_target"], plan["target_exposure"], "PRIOR_CLOSE_HELD_TARGET")
    desired = {s: number(q) for s, q in plan["desired_basket"].items()}
    core = {s: number(q) for s, q in plan["canonical_target_shares"].items()}
    for event in events:
        sid, kind = event["security_id"], event["event_type"]
        if kind == "CASH_MERGER":
            desired.pop(sid, None)
            core.pop(sid, None)
        elif kind == "CONVERSION":
            need(day == "2018-09-04" and event["ticker"] == "ILG", "DECLARED_MATERIAL_BRIDGE_ONLY")
            detail = event["detail"]
            delivered = detail["delivered_security_id"]
            if sid in desired:
                entitlement = desired.pop(sid) * number(detail["exchange_ratio_exact"])
                desired[delivered] = Fraction(entitlement.numerator // entitlement.denominator)
            core.pop(sid, None)
            core[delivered] = number(str(detail["shares_delivered"]))
    entry_audit = []
    for intent in plan["opening_intents"]:
        sid = intent["security_id"]
        buys = [e for e in events if e["event_type"] == "BUY" and e["security_id"] == sid]
        need(len(buys) == 1, "FIXED_PILOT_ORIGINAL_OPENING_FILL_COVERAGE")
        source = buys[0]
        equal_number(str(source["price"]), opens[sid], "ENTRY_ACTUAL_RAW_OPEN")
        quantity = api.opening_quantity(intended=float(intent["intended_dollars"]),
            cash=float(source["cash_before"]), price=float(source["price"]), cost_bps=10)
        equal_number(str(source["shares_delta"]), quantity, "CANONICAL_FIXED_CORE_OPENING_QUANTITY")
        desired[sid] = Fraction((number(quantity) * number(plan["target_exposure"]) *
                                number(plan["nav"]) / number(plan["core_nav"])) // 1)
        core[sid] = number(quantity)
        entry_audit.append({"intent": intent, "status": "SOURCE_FILLED", "source_buy": source,
                            "canonical_core_shares": quantity, "account_shares": str(desired[sid])})
    need(execution["intended_entry_sizing"] == entry_audit, "ORIGINAL_DOLLAR_ENTRY_GEOMETRY")
    references = dict(plan["closing_marks"])
    for intent in plan["opening_intents"]:
        if intent["security_id"] in opens:
            references[intent["security_id"]] = opens[intent["security_id"]]
    for event in events:
        if event["event_type"] == "CONVERSION":
            references.pop(event["security_id"], None)
            new = event["detail"]["delivered_security_id"]
            references[new] = opens[new]
    audit = execution["headroom_audit"]
    number_map(audit["marks"], references, "OPEN_HEADROOM_BOUND_MARKS")
    number_map(audit["canonical_target_shares"], core, "OPEN_HEADROOM_ORIGINAL_CORE_TARGET")
    need(audit["opening_intents"] == plan["opening_intents"], "OPEN_HEADROOM_INTENTS")
    quantities = {s: api.exact_decimal(q) for s, q in desired.items() if s != BIL and q > 0}
    projection = api.Projection(target_exposure=Decimal(plan["target_exposure"]),
        nav=api.exact_decimal(number(plan["nav"])), quantities=quantities,
        notional={s: api.exact_decimal(number(q) * number(references[s])) for s, q in quantities.items()},
        defensive_security=BIL, defensive_quantity=api.exact_decimal(desired.get(BIL, Fraction(0))))
    need(projection.to_dict() == audit["raw_projection"], "OPEN_RAW_HEADROOM_INPUT")
    retained = plan["retained_targets"]
    if retained is not None:
        retained = {s: Decimal(q) for s, q in retained.items() if s in quantities or s == BIL}
        for event in events:
            if event["event_type"] == "CONVERSION":
                retained.pop(event["security_id"], None)
                new = event["detail"]["delivered_security_id"]
                if new in desired:
                    retained[new] = api.exact_decimal(desired[new])
    if retained is None:
        need(audit["retained_targets"] is None, "OPEN_Q_RETENTION_DISABLED")
    else:
        number_map(audit["retained_targets"], retained, "OPEN_MATERIAL_UNIT_BRIDGE")
    target = api.ShadowTarget(shares={s: api.exact_decimal(q) for s, q in core.items()},
        tickers={}, opening_intents=tuple(api.OpeningIntent(i["security_id"], i["slot_id"],
        Decimal(i["intended_dollars"])) for i in plan["opening_intents"]))
    final = api.apply(projection, targets=retained, canonical_target=target,
                      marks={s: Decimal(p) for s, p in references.items()})
    need(final.to_dict() == audit["final_projection"], "CANONICAL_OPEN_HEADROOM")
    wanted = {**{s: str(q) for s, q in final.quantities.items()}, BIL: str(final.defensive_quantity)}
    number_map(execution["desired_basket"], wanted, "EXECUTABLE_TARGET_INTENT")
    state = check_snapshot(record["snapshot"])
    actual = {p["security_id"]: p["shares"] for p in state["positions"].values()}
    number_map(execution["actual_shares"], actual, "ACTUAL_VERSUS_TARGET_SHARES")
    remaining = {s: number(q) - number(actual.get(s, "0")) for s, q in wanted.items()}
    number_map(execution["remaining"], remaining, "UNFILLED_INTENT_NOT_REPLACED_BY_FILL")


def validate_event_source(item: dict, original_events: list[dict], all_events: list[dict],
                          bil: dict, prior: dict | None) -> None:
    event, context = item["record"]["event"], item["context"]
    operation, day = event["operation"], event["session"]
    source = context.get("source_event")
    if source is not None:
        need(source in original_events and context["source_event_sha256"] == digest(source),
             "IMMUTABLE_SOURCE_ACTION_EVENT")
    if operation in ("BUY", "SELL"):
        need(prior is not None, "NO_ANCHOR_TRADE")
        for field in ("state_sha256", "input_sha256"):
            need(context["source_" + field] == prior["pending"]["source_" + field],
                 "TRADE_PRECOMMITTED_SOURCE")
        quote = context["quote"]
        need(quote["domain"] == "RAW_OPEN" and quote["security_id"] == event["security_id"] and
             quote["session"] == day, "TRADE_RAW_QUOTE_IDENTITY")
        equal_number(quote["price"], event["raw_price"], "TRADE_RAW_QUOTE_PRICE")
        converted = {e["detail"]["delivered_security_id"] for e in original_events
                     if e["event_type"] == "CONVERSION"}
        sid = event["security_id"]
        live = sid == BIL or sid in prior["pending"]["ownership"] or sid in converted
        need(context["intent"]["core_exit"] == (operation == "SELL" and not live),
             "RETIRE_ONLY_FIXED_CORE_EXIT")
    elif operation == "DIVIDEND_ACCRUED":
        terms = context["dividend_terms"]
        sid = event["security_id"]
        if sid == BIL:
            action = context["bil_action"]
            need(action in bil["actions"] and context["bil_action_sha256"] == digest(action),
                 "BOUND_BIL_CASH_DISTRIBUTION")
            expected = {"security_id": BIL, "ex_date": action["ex_date"],
                        "pay_date": action["payable_date"], "cash_per_share": str(action["rate"])}
            need(event["claim_id"] == "BIL/" + str(action["id"]), "EXACT_BIL_CLAIM_ID")
        else:
            need(source is not None and source["event_type"] == "DIVIDEND_ACCRUED", "SOURCE_CORE_EX_DATE")
            payments = [e for e in all_events if e["event_type"] == "DIVIDEND_PAID" and
                        e["security_id"] == sid and e["detail"]["accrued_session"] == day]
            need(len(payments) == 1, "SOURCE_CORE_PAY_DATE")
            expected = {"security_id": sid, "ex_date": day, "pay_date": payments[0]["session"],
                        "cash_per_share": str(source["price"])}
            need(event["claim_id"] == sid + "/" + day, "EXACT_CORE_CLAIM_ID")
        need(terms["security_id"] == expected["security_id"] and terms["ex_date"] == expected["ex_date"] and
             terms["pay_date"] == expected["pay_date"], "AUTHENTICATED_EX_AND_PAY_TERMS")
        equal_number(terms["cash_per_share"], expected["cash_per_share"], "AUTHENTICATED_DIVIDEND_RATE")
    elif operation == "CASH_MERGER":
        need(source is not None and source["event_type"] == "CASH_MERGER", "SOURCE_CASH_SETTLEMENT")
        equal_number(event["cash_per_share"], str(source["price"]), "SOURCE_CASH_MERGER_RATE")
    elif operation == "CONVERSION":
        need(source is not None and source["event_type"] == "CONVERSION" and day == "2018-09-04" and
             source["ticker"] == "ILG", "EXACT_DECLARED_ILG_ACTION")
        terms = event["terms"]
        need(terms["delivered_security_id"] == source["detail"]["delivered_security_id"], "DELIVERED_VAC_IDENTITY")
        for value, expected in ((terms["ratio"], source["detail"]["exchange_ratio_exact"]),
                                (terms["cash_per_share"], str(source["price"])),
                                (terms["cil_price"], str(source["detail"]["reference_rebase"]["delivered_raw_open"]))):
            equal_number(value, expected, "AUTHENTICATED_ILG_TERMS")
    elif operation == "SPLIT":
        need(source is not None and source["event_type"] == "SPLIT", "SOURCE_SHARE_UNIT_ACTION")
        equal_number(event["ratio"], str(source["detail"]["ratio"]), "SOURCE_SPLIT_RATIO")
    elif operation == "CORE_EXIT_RETIRED":
        need(prior is not None, "RETIREMENT_HAS_SOURCE_PREDECESSOR")
        matches = [sid for sid, meta in prior["pending"]["identities"].items()
                   if meta["episode"] == event["episode"]]
        need(len(matches) == 1 and matches[0] not in prior["pending"]["ownership"] and
             context["source_state_sha256"] == prior["pending"]["source_state_sha256"],
             "RETIREMENT_ONLY_IMMUTABLE_CORE_EXIT")


def summary_metrics(series: list[tuple[str, str]]) -> dict:
    values = [(day, number(value)) for day, value in series]
    high, peak = values[0][1], values[0][0]
    worst, worst_peak, trough = Fraction(0), peak, peak
    for day, nav in values:
        if nav >= high:
            high, peak = nav, day
        draw = 1 - nav / high
        if draw > worst:
            worst, worst_peak, trough = draw, peak, day
    return {"first": START, "last": END, "closes": COUNT, "start_nav": "50000",
            "end_nav": str(values[-1][1]), "return_fraction": str(values[-1][1] / 50000 - 1),
            "maximum_drawdown": str(worst), "drawdown_peak": worst_peak, "drawdown_trough": trough}


def underwater(series: list[tuple[str, str]]) -> dict:
    high, peak_index, run, longest = number(series[0][1]), 0, 0, 0
    runs = []
    for i, (day, raw) in enumerate(series):
        nav = number(raw)
        if nav >= high:
            if run:
                runs.append({"peak": series[peak_index][0], "recovery": day,
                             "underwater_closes": run, "censored": False})
            high, peak_index, run = nav, i, 0
        else:
            run += 1
            longest = max(longest, run)
    if run:
        runs.append({"peak": series[peak_index][0], "recovery": None,
                     "through": series[-1][0], "underwater_closes": run, "censored": True})
    return {"longest_underwater_closes": longest, "episodes": runs}


def verify_trade_sequence(before: dict, execution: dict, items: list[dict], opens: dict) -> None:
    wanted = {s: number(q) for s, q in execution["desired_basket"].items()}
    actual = {p["security_id"]: number(p["shares"]) for p in before["positions"].values()}
    need(len(actual) == len(before["positions"]), "UNIQUE_FUNDED_SECURITY_LOT")
    cash, expected = number(before["cash"]), []
    for sid in sorted(set(actual) | set(wanted)):
        have, want = actual.get(sid, Fraction(0)), wanted.get(sid, Fraction(0))
        if have > want:
            quantity = have - want
            expected.append((sid, "SELL", quantity))
            cash += quantity * number(opens[sid]) * (1 - FEE)
            actual[sid] = want
    for sid in sorted(wanted):
        have, want = actual.get(sid, Fraction(0)), wanted[sid]
        if want > have:
            quantity = Fraction((want - have) // 1)
            if quantity:
                expected.append((sid, "BUY", quantity))
                fill = min(quantity, Fraction(cash // (number(opens[sid]) * (1 + FEE))))
                cash -= fill * number(opens[sid]) * (1 + FEE)
                actual[sid] = have + fill
    observed = [(item["record"]["event"]["security_id"], item["record"]["event"]["operation"],
                 number(item["record"]["event"]["requested_shares"])) for item in items]
    need(observed == expected, "EVERY_TARGET_DELTA_SELL_BEFORE_BUY_SID_ORDER")
    need(execution["fills"] == [item["record"]["event"] for item in items], "EXECUTION_FILL_JOURNAL")


def journals_check(proof: dict, observed: dict) -> None:
    for key in ("records", "bytes", "file_sha256"):
        need(proof[key] == observed[key], "JOURNAL_COMMITMENT_" + key)
    need(proof["sha256"] == observed["prefix_sha256"], "JOURNAL_PLAINTEXT_PREFIX")


def prefixes(rows: list[dict], key: str) -> dict:
    h, count, size, result = hashlib.sha256(), 0, 0, {}
    for row in rows:
        raw = encoded(row) + b"\n"
        h.update(raw)
        count += 1
        size += len(raw)
        result[row[key]] = {"records": count, "bytes": size, "sha256": h.hexdigest()}
    return result


def failure_required(call, message: str) -> None:
    try:
        call()
    except (ValueError, TypeError, KeyError, AssertionError):
        return
    raise ValueError("FALSIFIER_NOT_DETECTED:" + message)


def review(args: argparse.Namespace) -> None:
    hosted(args)
    need(not args.output.exists(), "NEW_REVIEW_OUTPUT_REQUIRED")
    manifest = validate_manifest(args)
    originals, source_events, checkpoint = source_rows(args)
    sessions = [r["session"] for r in originals]
    bil, bil_review = verify_bil(args.input, sessions)
    bars = bil["daily"]
    proof, summary = read_json(args.work / "worker-proof.json"), read_json(args.work / "summary.json")
    need(proof["status"] == summary["status"] == "COMPLETE_REVIEW_REQUIRED" and
         proof["closes"] == COUNT and proof["Core_steps"] == proof["Sentinel_steps"] == 0,
         "FIXED_COMPLETE_WORKER_SCOPE")
    source_proof = {"checkpoint_sha256": CHECKPOINT_SHA, "daily_sha256": P00_DAILY_SHA,
                    "daily_bytes": P00_DAILY_BYTES, "checkpoint_inner_sha256": checkpoint["sha256"],
                    "immutable_decisions_sha256": digest([r["decision"] for r in originals])}
    need(proof["source"] == source_proof and proof["scalar_proof"]["source"] == source_proof,
         "EXACT_WORKER_ORIGINAL_SOURCE")
    need(proof["input"]["manifest_sha256"] == file_sha(args.input / "manifest.json") and
         proof["input"]["protocol_sha256"] == manifest["protocol_sha256"], "WORKER_INPUT_AUTHORITY")
    bil_proof = {"file_sha256": file_sha(args.input / "bil-input.json"), "schema": bil["schema"],
                 "qualification": bil["qualification"]}
    need(proof["bil"] == bil_proof and proof["scalar_proof"]["bil"] == bil_proof,
         "SAME_QUALIFIED_BIL_SOURCE")
    need(proof["worker_sha256"] == file_sha(args.current / "research/persistent_share_reconciliation/worker.py"),
         "ACTUAL_WORKER_SOURCE")
    for name, expected in proof["source_files"].items():
        path = Path(name)
        need(any(path.is_relative_to(root) for root in (args.current, args.legacy)) and
             file_sha(path) == expected, "ACTUAL_BOUND_FINANCIAL_SOURCE")
    identity = digest({"source": source_proof, "bil": bil_proof, "files": proof["source_files"],
                       "worker_sha256": proof["worker_sha256"],
                       "input_manifest_sha256": proof["input"]["manifest_sha256"],
                       "protocol_sha256": proof["input"]["protocol_sha256"]})
    need(identity == proof["identity"], "INDEPENDENT_STUDY_IDENTITY")
    identities = {arm: digest({"study_identity": identity, "arm": arm}) for arm in ("Q", "P")}
    need(proof["account_identities"] == identities and identities["Q"] != identities["P"],
         "CROSS_ARM_ACCOUNT_SOURCE_SEPARATION")
    data = {}
    for key, filename in (("daily", "daily.jsonl.gz"), ("events", "events.jsonl.gz"),
                          ("trace", "source-trace.jsonl.gz"), ("checkpoints", "checkpoints.jsonl.gz")):
        values, commitment = read_journal(args.work / filename)
        journals_check(proof["journals"][key], commitment)
        data[key] = values
    daily, traces, account_events, saved_checkpoints = (data[k] for k in ("daily", "trace", "events", "checkpoints"))
    need([r["session"] for r in daily] == [r["session"] for r in traces] == sessions,
         "EXACT_DAILY_AND_TRACE_AXES")
    for arm in ("S", "A"):
        scalar_rows, commitment = read_journal(args.work / "scalar" / (arm + ".jsonl.gz"))
        journals_check(proof["scalar_proof"]["journals"][arm], commitment)
        need(scalar_rows == [r["arms"][arm] for r in daily], "ALL_SCALAR_JOURNAL_FIELDS")
    need(proof["scalar_proof"]["no_strategy_steps"] is True and
         proof["scalar_proof"]["imported_shadow_observation"] == "/variant/sentinel/shadow_observation.py",
         "FROZEN_SCALAR_IMPORT_NAMESPACE")
    synthetic = read_json(args.work / "synthetic-proof.json")
    need(synthetic == proof["synthetic_tests"] and synthetic["status"] == "PASS" and
         synthetic["actual_hosted_financial_calls"] is True and
         {"removed_apply", "removed_exposure_guard"} <= set(synthetic["guard_mutants_detected"]),
         "ACTUAL_HOSTED_SYNTHETICS_REQUIRED")

    # The canonical modules are imported only after the hosted/context and all
    # immutable input/source checks above. No worker implementation is imported.
    sys.path[:0] = [str(args.current), str(args.current / "shared"),
                    str(args.legacy / "research/capital_risk"), str(args.legacy)]
    os.environ["HOLDING_QUAL_HOSTED"] = "1"
    from sentinel.execution import projection as canonical_projection
    from sentinel.execution import held_targets
    from sentinel.execution.numeric import exact_decimal
    from sentinel.core.decision import ShadowTarget
    from sentinel.execution.plan import OpeningIntent
    from stock_strategy_shared.wealth_core.v5 import opening_quantity
    from holding_account import restore, snapshot
    need(Path(canonical_projection.__file__).resolve() == args.current / "sentinel/execution/projection.py" and
         Path(held_targets.__file__).resolve() == args.current / "sentinel/execution/held_targets.py",
         "CURRENT_CANONICAL_IMPORT_NAMESPACE")
    api = SimpleNamespace(project=canonical_projection.project, Projection=canonical_projection.Projection,
        desired_basket=canonical_projection.desired_basket, carry_quantities=held_targets.carry_quantities,
        apply=held_targets.apply, ownership=held_targets.ownership, exact_decimal=exact_decimal,
        ShadowTarget=ShadowTarget, OpeningIntent=OpeningIntent, opening_quantity=opening_quantity)
    states, fees, traded = {}, {}, {}
    for arm in ("Q", "P"):
        initial = check_snapshot(proof["initial_accounts"][arm])
        need(initial["source_sha256"] == identities[arm] and number(initial["cash"]) == 50000 and
             initial["positions"] == initial["claims"] == {} and initial["retired"] == [] and
             initial["applied_events"] == [] and initial["last_session"] is None and
             initial["chain_sha256"] == "0" * 64, "FLAT_UNFUNDED_ACCOUNT_ORIGIN")
        states[arm], fees[arm], traded[arm] = initial, Fraction(0), Fraction(0)
    by_day = {}
    for event in source_events:
        by_day.setdefault(event["session"], []).append(event)
    event_groups = {}
    for item in account_events:
        need(item["arm"] in ("Q", "P"), "REGISTERED_EVENT_ARM")
        key = item["record"]["event"]["session"], item["arm"]
        event_groups.setdefault(key, []).append(item)
    need(all(day in sessions[1:] for day, _ in event_groups), "NO_OUTSIDE_OR_ANCHOR_EVENT")
    series = {arm: [] for arm in ARMS}
    contexts = {}
    tested_projection = None
    previous_bar_day = "2017-12-29"
    for index, (original, trace, row) in enumerate(zip(originals, traces, daily, strict=True)):
        day = original["session"]
        source_day = by_day.get(day, [])
        need(trace["original_row"] == original and trace["source_record_sha256"] == digest(original) and
             trace["source_events"] == source_day and trace["bil_bar"] == bars[day],
             "IMMUTABLE_FULL_SOURCE_TRACE")
        need(trace["bil_actions"] == [a for a in bil["actions"]
             if a["ex_date"] == day or a["payable_date"] == day], "BIL_ACTION_SOURCE_TRACE")
        audit = original["evidence"]["research_entry_audit"]
        opens = {s: str(p["raw_price"]) for s, p in audit["opening_accounting"]["prices"].items()
                 if p["status"] == "RAW_OPEN"}
        closes = {s: str(p["raw_price"]) for s, p in audit["closing_accounting"]["prices"].items()
                  if p["status"] == "CURRENT"}
        for event in source_day:
            if event["event_type"] == "BUY":
                sid, price = event["security_id"], str(event["price"])
                if sid in opens:
                    equal_number(opens[sid], price, "SOURCE_OPEN_FILL_CORROBORATION")
                opens[sid] = price
        opens[BIL], closes[BIL] = bars[day]["raw_open"], bars[day]["raw_close"]
        number_map(trace["prices"]["raw_open"], opens, "IMMUTABLE_RAW_OPEN_PACKET")
        number_map(trace["prices"]["raw_close"], closes, "IMMUTABLE_RAW_CLOSE_PACKET")
        need(row["decision_sha256"] == digest(original["decision"]) and set(row["arms"]) == set(ARMS),
             "ALL_ARMS_SAME_DECISION")
        for key in ("state_sha256", "input_sha256", "chain_sha256"):
            need(row["source_" + key] == original[key], "DAILY_IMMUTABLE_SOURCE")
        equal_number(row["close_target"], str(original["decision"]["target_core_exposure"]), "DAILY_FIXED_TARGET")
        for arm in ("S", "A"):
            economics = row["arms"][arm]["economics"]
            need(row["arms"][arm]["arm"] == arm and row["arms"][arm]["session"] == day, "SCALAR_ARM_AXIS")
            if arm == "S":
                need(economics == original["economics"], "EXACT_S_EVERY_ECONOMICS_FIELD")
            if arm == "A":
                verify_a_metadata(economics, bars, day, previous_bar_day, index, original)
            if index:
                prior = daily[index - 1]["arms"][arm]["economics"]
                expected = scalar_factor(prior, original, economics, source_events)
                for key, value in expected.items():
                    need(abs(Decimal(economics[key]) - value) < Decimal("1e-22"), "INDEPENDENT_SCALAR_FACTOR:" + key)
                with localcontext() as context:
                    context.prec = 28
                    expected_nav = format((Decimal(prior["strategy_nav"]) * Decimal(economics["net_factor"])).normalize(), "f")
                need(economics["strategy_nav"] == expected_nav, "INDEPENDENT_SCALAR_VALUE_STEP")
                equal_number(economics["held_allocation"], prior["pending_allocation"], "SCALAR_NEXT_OPEN_TARGET")
            else:
                equal_number(economics["strategy_nav"], 50000, "SCALAR_UNFUNDED_ANCHOR")
            equal_number(economics["pending_allocation"], row["close_target"], "SCALAR_FIXED_FUTURE_TARGET")
            series[arm].append((day, economics["strategy_nav"]))
        for arm in ("Q", "P"):
            account = row["arms"][arm]
            prior_record = daily[index - 1]["arms"][arm] if index else None
            events = event_groups.get((day, arm), [])
            pre_open = deepcopy(states[arm])
            first_trade_state, saw_trade, trades = None, False, []
            expected_ex = {(e["security_id"], day) for e in source_day if e["event_type"] == "DIVIDEND_ACCRUED" and
                           any(p["security_id"] == e["security_id"] for p in pre_open["positions"].values())}
            required_material = [e for e in source_day if e["event_type"] in ("CONVERSION", "CASH_MERGER", "SPLIT")
                                 and any(p["security_id"] == e["security_id"] for p in pre_open["positions"].values())]
            observed_material = []
            if any(p["security_id"] == BIL for p in pre_open["positions"].values()):
                expected_ex.update((BIL, day) for a in bil["actions"] if a["ex_date"] == day)
            observed_ex = []
            for item in events:
                operation = item["record"]["event"]["operation"]
                need(item["before_state_sha256"] == digest(states[arm]), "EVENT_STATE_PREDECESSOR_HASH")
                if operation in ("BUY", "SELL"):
                    if first_trade_state is None:
                        first_trade_state = deepcopy(states[arm])
                    saw_trade = True
                    trades.append(item)
                elif operation != "CORE_EXIT_RETIRED":
                    need(not saw_trade, "EX_DATE_AND_ACTIONS_BEFORE_NEW_OPEN_FILLS")
                validate_event_source(item, source_day, source_events, bil, prior_record)
                if operation in ("BUY", "DIVIDEND_ACCRUED", "DIVIDEND_PAID") and operation not in contexts:
                    contexts[operation] = (deepcopy(states[arm]), deepcopy(item),
                                           {s: {"raw_open": p} for s, p in opens.items()})
                states[arm] = replay_event(states[arm], item, {s: {"raw_open": p} for s, p in opens.items()})
                event = item["record"]["event"]
                if operation == "DIVIDEND_ACCRUED":
                    observed_ex.append((event["security_id"], day))
                if operation in ("CONVERSION", "CASH_MERGER", "SPLIT"):
                    observed_material.append(item["context"]["source_event"])
                fees[arm] += number(event.get("fees", "0"))
                if operation in ("BUY", "SELL"):
                    traded[arm] += number(event["filled_shares"]) * number(event["raw_price"])
            need(set(observed_ex) == expected_ex and len(observed_ex) == len(expected_ex),
                 "EVERY_HELD_EX_DATE_ENTITLEMENT_EXACTLY_ONCE")
            need(observed_material == required_material, "EVERY_HELD_MATERIAL_ACTION")
            need(all(c["pay_session"] > day for c in states[arm]["claims"].values()), "EVERY_DUE_CLAIM_PAID_ONCE")
            need(check_snapshot(account["snapshot"]) == states[arm], "INDEPENDENT_FULL_CLOSING_ACCOUNT")
            need(states[arm]["source_sha256"] == identities[arm], "DAILY_ACCOUNT_ARM_IDENTITY")
            number_map(account["marks"], closes, "DAILY_ORIGINAL_CLOSE_MARKS")
            nav = account_nav(states[arm], closes)
            sizing = account_nav(states[arm], closes, claims=False)
            for key, value in (("nav", nav), ("sizing_nav", sizing), ("cash", states[arm]["cash"]),
                               ("claims_value", nav - sizing), ("cumulative_fees", fees[arm]),
                               ("cumulative_traded_notional", traded[arm])):
                equal_number(account[key], value, "DAILY_ACCOUNT_IDENTITY:" + key)
            previous_nav = number(prior_record["nav"]) if prior_record else Fraction(50000)
            equal_number(account["previous_nav"], previous_nav, "PREVIOUS_ACCOUNT_NAV")
            equal_number(account["net_factor"], nav / previous_nav, "EXACT_SHARE_ACCOUNT_NET_FACTOR")
            need(nav > 0, "POSITIVE_UNLEVERED_NAV")
            holdings = {h["episode"]: h for h in account["holdings"]}
            need(len(holdings) == len(account["holdings"]) and
                 set(holdings) == set(states[arm]["positions"]), "COMPLETE_HOLDINGS_REPORT")
            for key, position in states[arm]["positions"].items():
                held = holdings[key]
                for field in ("episode", "security_id", "ticker", "kind"):
                    need(held[field] == position[field], "HOLDING_IDENTITY_REPORT")
                equal_number(held["shares"], position["shares"], "HOLDING_QUANTITY_REPORT")
                equal_number(held["raw_close"], closes[position["security_id"]], "HOLDING_RAW_MARK_REPORT")
                equal_number(held["value"], number(position["shares"]) * number(closes[position["security_id"]]),
                             "HOLDING_NOTIONAL_REPORT")
            if index:
                verify_open(original, account, prior_record, source_day, opens, api)
                verify_trade_sequence(first_trade_state or states[arm], account["execution"], trades, opens)
            else:
                need(account["execution"] is None and not events and nav == 50000, "NO_PRE_ANCHOR_HOLDING_OR_GAP")
            verify_projection(original, arm, account, prior_record, closes,
                              sessions[index + 1] if index + 1 < COUNT else None, api)
            if arm == "P" and index and account["projection_audit"]["retained_targets"]:
                tested_projection = (original, arm, account, prior_record, closes,
                                     sessions[index + 1] if index + 1 < COUNT else None)
            series[arm].append((day, account["nav"]))
        previous_bar_day = day

    # Every checkpoint is checked against the independently reconstructed daily
    # account and the immutable source, including complete wrapper lineage.
    daily_prefix = prefixes(daily, "session")
    event_prefix_rows = [{"session": item["record"]["event"]["session"], "item": item} for item in account_events]
    event_prefix = {}
    h, size = hashlib.sha256(), 0
    for i, wrapper in enumerate(event_prefix_rows, start=1):
        raw = encoded(wrapper["item"]) + b"\n"
        h.update(raw)
        size += len(raw)
        event_prefix[wrapper["session"]] = {"records": i, "bytes": size, "sha256": h.hexdigest()}
    required, previous_ownership, previous_target = set(), None, None
    for i, item in enumerate(daily):
        own = item["arms"]["P"]["pending"]["ownership"]
        if (i == COUNT - 1 or item["session"][:7] != daily[i + 1]["session"][:7] or
                own != previous_ownership or item["close_target"] != previous_target):
            required.update((item["session"], arm) for arm in ("Q", "P"))
        previous_ownership, previous_target = own, item["close_target"]
    need({(cp["session"], cp["checkpoint"]["arm"]) for cp in saved_checkpoints} == required and
         len(saved_checkpoints) == len(required), "ALL_REQUIRED_CHECKPOINT_BOUNDARIES")
    checkpoint_chain = {arm: "0" * 64 for arm in ("Q", "P")}
    by_session = {r["session"]: r for r in daily}
    last_event_prefix = {"records": 0, "bytes": 0, "sha256": hashlib.sha256().hexdigest()}
    event_at_close = {}
    for day in sessions:
        last_event_prefix = event_prefix.get(day, last_event_prefix)
        event_at_close[day] = last_event_prefix
    for item in saved_checkpoints:
        cp, day = item["checkpoint"], item["session"]
        arm, observed = cp["arm"], by_session[day]["arms"][cp["arm"]]
        need(cp["schema"] == "research.fixed-share-reconciliation-checkpoint/1" and
             cp["source_sha256"] == identities[arm] and cp["account"] == observed["snapshot"] and
             cp["pending"] == observed["pending"], "CHECKPOINT_COMPLETE_ACCOUNT_INTENT")
        expected_plan = {"target_exposure": observed["pending"]["target_exposure"],
                         "decision_session": day, "target_basket": observed["pending"]["desired_basket"],
                         "opening_intents": observed["pending"]["opening_intents"]}
        expected_projection = {"target_basket": observed["pending"]["desired_basket"],
                               "through_session": day, "action_multipliers": {}, "action_evidence": []}
        need(cp["previous_state"] == observed["projection_audit"]["state"] and
             cp["previous_plan"] == expected_plan and cp["previous_projection"] == expected_projection,
             "CHECKPOINT_ALL_CONTINUATION_STATE")
        for key, source_key in (("last_nav", "nav"), ("cumulative_fees", "cumulative_fees"),
                                ("cumulative_traded_notional", "cumulative_traded_notional")):
            equal_number(cp[key], observed[source_key], "CHECKPOINT_FINANCIAL_CONTINUATION")
        need(cp["previous_checkpoint_sha256"] == checkpoint_chain[arm] and
             cp["checkpoint_sha256"] == digest({k: v for k, v in cp.items() if k != "checkpoint_sha256"}),
             "CHECKPOINT_WRAPPER_CHAIN")
        checkpoint_chain[arm] = cp["checkpoint_sha256"]
        need(item["daily_prefix"] == daily_prefix[day] and cp["event_prefix"] == event_at_close[day] and
             item["source_state_sha256"] == observed["pending"]["source_state_sha256"],
             "CHECKPOINT_SOURCE_AND_JOURNAL_PREFIXES")
        need(snapshot(restore(cp["account"], identities[arm])) == cp["account"], "INDEPENDENT_ACTUAL_ACCOUNT_RESTORE")
    independent = {}
    for arm in ARMS:
        expected = summary_metrics(series[arm])
        if arm in ("Q", "P"):
            expected.update(fees=str(fees[arm]), traded_notional=str(traded[arm]),
                            restores=sum(cp["checkpoint"]["arm"] == arm for cp in saved_checkpoints))
        need(summary["arms"][arm] == expected, "INDEPENDENT_FULL_PILOT_METRICS:" + arm)
        independent[arm] = {**expected, "underwater": underwater(series[arm])}
    need(summary["attribution"] == ["S_TO_A_DEFENSIVE_SOURCE", "A_TO_Q_ACCOUNT_GEOMETRY_AND_CONVENTIONS",
                                    "Q_TO_P_PERSISTENCE"] and summary["performance_admitted"] is False,
         "DECLARED_BRIDGES_NOT_STRATEGY_SELECTION")

    # These corruptions are evaluated only here, inside the admitted offline
    # hosted reviewer. They never execute financial logic on the local host.
    falsifiers = []
    mixed_anchor = deepcopy(daily[0]["arms"]["A"]["economics"])
    mixed_anchor["bil_open_adjusted"] = originals[0]["economics"]["bil_open_adjusted"]
    failure_required(lambda: verify_a_metadata(mixed_anchor, bars, START, "2017-12-29", 0, originals[0]),
                     "mixed_A_anchor_price_metadata")
    falsifiers.append("mixed_A_anchor_price_metadata")
    custom_protected_dto = deepcopy(daily[-1]["arms"]["P"])
    custom_protected_dto["projection_audit"]["predecessor_projection"]["opening_sizing"] = {
        "mode": "TRACE_DTO_IDEALIZED_RAW_OPEN", "entries": []}
    failure_required(lambda: verify_projection(originals[-1], "P", custom_protected_dto,
        daily[-2]["arms"]["P"], custom_protected_dto["marks"], None, api),
                     "research_metadata_in_protected_projection_field")
    falsifiers.append("research_metadata_in_protected_projection_field")
    for operation, label in (("BUY", "overspend_or_altered_fill"),
                             ("DIVIDEND_ACCRUED", "duplicate_entitlement"),
                             ("DIVIDEND_PAID", "early_payment")):
        need(operation in contexts, "ACTUAL_EVENT_FALSIFIER_COVERAGE:" + operation)
        before, item, prices = deepcopy(contexts[operation])
        event = item["record"]["event"]
        if operation == "BUY":
            event["filled_shares"] = str(number(event["filled_shares"]) + 1)
        elif operation == "DIVIDEND_ACCRUED":
            before["claims"][event["claim_id"]] = deepcopy(item["record"]["state_without_chain"]["claims"][event["claim_id"]])
        else:
            from datetime import timedelta
            before["claims"][event["claim_id"]]["pay_session"] = (
                date.fromisoformat(event["session"]) + timedelta(days=1)).isoformat()
        failure_required(lambda: replay_event(before, item, prices), label)
        falsifiers.append(label)
    corrupt = deepcopy(daily[-1]["arms"]["P"]["snapshot"])
    corrupt["state"]["cash"] = "-1"
    failure_required(lambda: check_snapshot(corrupt), "corrupted_or_negative_checkpoint")
    falsifiers.append("corrupted_or_negative_checkpoint")
    need(tested_projection is not None, "ACTUAL_RETENTION_FALSIFIER_COVERAGE")
    row, arm, observed, prior, marks, next_day = deepcopy(tested_projection)
    observed["projection_audit"]["retained_targets"] = {}
    failure_required(lambda: verify_projection(row, arm, observed, prior, marks, next_day, api),
                     "removed_retention")
    falsifiers.append("removed_retention")
    altered = deepcopy(daily[-1]["arms"]["P"]["projection_audit"])
    altered["previous_plan"]["target_exposure"] = ".123"
    copy_record = deepcopy(daily[-1]["arms"]["P"])
    copy_record["projection_audit"] = altered
    failure_required(lambda: verify_projection(originals[-1], "P", copy_record,
        daily[-2]["arms"]["P"], daily[-1]["arms"]["P"]["marks"], None, api), "altered_source_predecessor")
    falsifiers.append("altered_source_predecessor")
    args.output.mkdir(parents=True, exist_ok=False)
    output = {"status": "FIXED_ACCOUNT_RECONCILIATION_REVIEW_PASSED", "closes": COUNT,
        "arms": list(ARMS), "events_independently_replayed": len(account_events),
        "checkpoints_independently_restored": len(saved_checkpoints), "input_manifest_sha256": file_sha(args.input / "manifest.json"),
        "worker_proof_sha256": file_sha(args.work / "worker-proof.json"), "review_source_sha256": file_sha(Path(__file__)),
        "source": source_proof, "bil_source_review": bil_review, "reports": independent,
        "hosted_reviewer_falsifiers": {"status": "PASS", "detected": falsifiers},
        "canonical_projection_calls_verified": COUNT * 2, "canonical_open_headroom_calls_verified": (COUNT - 1) * 2,
        "exact_original_scalar_fields": COUNT, "new_Core_steps": 0, "new_Sentinel_steps": 0,
        "full_production_or_protected_fill_claim": False, "performance_admitted": False}
    (args.output / "independent-review.json").write_bytes(encoded(output) + b"\n")
    print(json.dumps({"status": output["status"], "closes": COUNT,
                      "events": len(account_events), "performance_admitted": False}), flush=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    for name in ("source", "legacy", "current", "p00", "input", "work", "output"):
        result.add_argument("--" + name, type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    hosted(args)
    review(args)


if __name__ == "__main__":
    main()
