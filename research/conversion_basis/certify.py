"""Two-session economic certificate using immutable replay inputs and local Core.

The external replay checkouts provide input readers only. All production modules
must resolve inside this checkout. No input/checkpoint/source is written.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal as D
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    for name in ("readers", "harness", "checkpoint", "archive", "sfp", "supplements", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root), str(root / "shared")]
    # Bind regular production packages before external input-reader imports.
    from sentinel.core.kernel import advance_session
    from sentinel.core.session import SessionState
    from sentinel.strategy import production_strategy
    from stock_strategy_shared.wealth_core.feed import Feed
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.ledger import Ledger

    sys.path.append(str(args.readers))
    saved_argv = sys.argv
    sys.argv = ["input-readers", "--harness", str(args.harness)]
    try:
        r = importlib.import_module("research.economic_replay60.run")
    finally:
        sys.argv = saved_argv
    # Reader bootstrap changes search paths; restore local priority as well.
    sys.path[:0] = [str(root), str(root / "shared")]
    pointer = json.loads(args.checkpoint.read_text())
    checkpoint = Path(pointer["path"])
    assert digest(checkpoint) == pointer["sha256"]
    packet = json.loads(gzip.decompress(checkpoint.read_bytes()))
    original = SessionState.from_dict(packet["state"])
    assert original.state_hash == packet["state_sha256"]
    assert original.last_processed_session == "2008-12-22"
    config, identity = production_strategy()
    # Explicit analytical fork. Never alter the retained checkpoint identity.
    fork = deepcopy(packet["state"])
    fork["strategy_identity"] = identity
    state = SessionState.from_dict(fork)
    data = r.JanuaryInputs(args.archive, args.sfp)
    supplements_sha = digest(args.supplements)
    supplements = json.loads(args.supplements.read_text())
    terminal = r.terminals(r.supplemented_terminals(data.rows("terminal-events.csv.gz")))
    spins = r.distributions(data.rows("actions.csv.gz"))
    cash_rows = {x["session"]: x for x in data.rows("cash.csv.gz")}
    meta = {sid: r.SecurityMeta(**v) for sid, v in packet["metadata"].items()}
    sectors, factors = deepcopy(packet["sectors"]), deepcopy(packet["factors"])
    economics = deepcopy(packet["economics"])
    source, delivered = "515130960484578865", "328265922479251290"
    report = {"scope": "Two-session analytical fork; no historical performance recertification",
              "checkpoint": pointer, "original_state_sha256": original.state_hash,
              "original_strategy_identity": original.strategy_identity,
              "fixed_strategy_identity": identity, "fork_state_sha256": state.state_hash,
              "archive_sha256": digest(args.archive), "supplements_sha256": supplements_sha,
              "sessions": []}
    account = r.EconomicPath(100000)
    for index, (day, rows) in enumerate(data.sessions(after=state.last_processed_session)):
        if index == 2:
            break
        assert day == ("2008-12-23", "2008-12-24")[index]
        for row in rows:
            sid = row["security_id"]
            meta[sid], sectors[sid] = r.metadata(row), row["ff12"] or None
        anchors = {x["security_id"]: r.FeedAnchor(x["security_id"], x["ticker"],
            meta[x["security_id"]].issuer_key()[0], factors.get(x["security_id"], 1.0))
            for x in rows if x["security_id"] not in state.feed["series"]}
        extra = r.terminals([x for x in supplements if x["effective_session"] == day]).get(day, ())
        ids = {x.security_id for x in extra}
        events = [x for x in terminal.get(day, ()) if x.security_id not in ids]+list(extra)
        days = r.previous_sessions(day, 253)
        published = r.PublishedSession(session=day, data_version=1,
            bars=[r.vendor(x) for x in rows], meta=meta, sectors=sectors,
            spy_closeadj=[float(data.benchmark[d]) for d in days], spy_sessions=days,
            spy_expected_sessions=days, feed_anchors=anchors, terminal_events=events,
            spinoff_distributions=spins.get(day, ()))
        if index == 0:
            assert not any(x.security_id == source for x in published.bars)
            with patch.object(Feed, "prior_conversion_basis", return_value=None):
                ablated = advance_session(state, published, controller_config=config,
                                          strategy_identity=identity)
            assert ablated.wealth_core["unresolved_terminals"][source] == "MISSING_CONVERSION_SIGNAL_BASIS"
            report["without_fix"] = ablated.last_evidence["wealth_core"]
        before_hash = state.state_hash
        candidate = advance_session(state, published, controller_config=config, strategy_identity=identity)
        restored = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
        restarted = advance_session(restored, published, controller_config=config, strategy_identity=identity)
        assert candidate.state_hash == restarted.state_hash
        assert state.state_hash == before_hash
        witness = candidate.last_evidence["wealth_core"]
        assert not witness["blocked"]
        book = PortfolioState.from_dict(candidate.wealth_core)
        marks = {x.security_id: D(str(x.raw_close)) for x in published.bars if x.raw_close}
        ledger = Ledger.from_dict(candidate.ledger)
        manual_close = D(str(book.cash)) + D(str(ledger.receivable_total()))
        manual_close += sum((D(str(ep.current_shares))*marks[ep.security_id]
                             for ep in book.episodes.values()), D(0))
        assert abs(manual_close-D(str(witness["resolved_equity"]))) < D("0.00000001")
        if index == 0:
            terms = next(x for x in events if x.security_id == source)
            quantity = D(70)*D("0.6272")
            shares = int(quantity)
            cash = D(70)*D("39.90")+(quantity-shares)*D("41.82")
            ep = next(x for x in book.episodes.values() if x.security_id == delivered)
            assert ep.current_shares == shares == 43
            assert abs(D(str(book.cash))-D(str(state.wealth_core["cash"]))-cash) < D("0.00000001")
            report["conversion"] = {"terms": asdict(terms), "source_shares": 70,
                "whole_delivered_shares": shares, "fraction": str(quantity-shares),
                "cash": str(cash), "cash_in_lieu_assumed_price": "41.82",
                "actual_cash_change": book.cash-state.wealth_core["cash"],
                "delivered_episode": asdict(ep)}
        gap, intraday = D(cash_rows[day]["gap_factor"]), D(cash_rows[day]["intraday_factor"])
        prices = {"bil_open_signal": str(gap), "bil_close_signal": str(gap*intraday),
            "bil_close_adjusted": str(gap*intraday), "bil_close_unadjusted": str(gap*intraday),
            "bil_previous_close_adjusted": "1", "bil_previous_session": r.previous_sessions(day, 2)[0]}
        economics = account.advance(previous=economics, state=candidate, strategy_prices=prices)
        report["sessions"].append({"session": day, "state_sha256": candidate.state_hash,
            "restart_parity": True, "prior_immutable": True, "manual_close_nav": str(manual_close),
            "wealth_core": witness, "economics": economics})
        state = candidate
        for row in rows:
            sid = row["security_id"]
            factors[sid] = factors.get(sid, 1.0)*r.number(row["split_ratio"])
    modules = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
               if (name == "sentinel" or name.startswith(("sentinel.", "stock_strategy_shared.")))
               and getattr(module, "__file__", None)}
    assert all(Path(path).is_relative_to(root) for path in modules.values())
    report["production_modules_local"] = True
    report["changed_source_files"] = {name: digest(root/name) for name in (
        "shared/stock_strategy_shared/wealth_core/adapter.py",
        "shared/stock_strategy_shared/wealth_core/feed.py",
        "shared/stock_strategy_shared/wealth_core/run.py")}
    assert original.state_hash == packet["state_sha256"]
    assert digest(checkpoint) == pointer["sha256"]
    assert digest(args.supplements) == supplements_sha
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({"result": "PASS", "output": str(args.output),
                      "sessions": [x["session"] for x in report["sessions"]]}))


if __name__ == "__main__":
    main()
