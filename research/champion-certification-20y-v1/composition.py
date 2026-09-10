"""Read-only daily composition evidence for the frozen research champion."""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
from pathlib import Path

SOURCE_SHA256 = "3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663"
MEASUREMENT_START = "2006-07-31"
LOOP_SEAM = "            pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d"
CALL = "            _cert_observe(locals())"
FIELDS = (
    "date", "phase", "security_id", "ticker", "bucket", "quantity", "lot_count",
    "mark", "mark_source", "metadata_effective_session", "security_type",
    "security_type_source", "reference_value", "core_equity",
    "shadow_weight_pct", "effective_exposure_pct", "effective_model_weight_pct",
    "close_desired_exposure_pct", "next_target_model_weight_pct",
)
SESSION_FIELDS = (
    "date", "phase", "core_equity", "stock_value", "cash", "receivables",
    "stock_count", "stock_lot_count", "held_ids_json", "effective_exposure_pct",
    "close_desired_exposure_pct", "shadow_weight_sum_pct",
    "effective_weight_sum_pct", "next_target_weight_sum_pct", "carried_mark_count",
    "unknown_canonical_type_count", "composition_sha256",
)
OBS_FIELDS = (
    "date", "measured", "dd", "r5", "r10", "r20", "r40", "dam", "green",
    "ddam5", "spy20", "volacc", "stops20", "nav", "open_eq", "close_eq",
    "recent_r20", "recent_r40", "current_native_close_target",
    "current_effective_native_preclose", "current_close_desired", "current_close_reason",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, *, positive=False):
    value = float(value)
    require(math.isfinite(value) and value >= 0 and (not positive or value > 0),
            f"invalid {name}: {value}")
    return value


def instrument(source: str) -> str:
    require(hashlib.sha256(source.encode()).hexdigest() == SOURCE_SHA256,
            "champion source hash mismatch")
    require(source.count(LOOP_SEAM) == 1 and "_cert_observe" not in source,
            "observer seam mismatch")
    result = source.replace(LOOP_SEAM, LOOP_SEAM + "\n" + CALL, 1)
    class StripObserver(ast.NodeTransformer):
        removed = 0
        def visit_Expr(self, node):
            if ast.dump(node) == ast.dump(ast.parse(CALL.strip()).body[0]):
                self.removed += 1
                return None
            return self.generic_visit(node)
    strip = StripObserver()
    stripped = strip.visit(ast.parse(result))
    require(strip.removed == 1 and ast.dump(stripped) == ast.dump(ast.parse(source)),
            "economic AST changed")
    compile(result, "<composition-observer>", "exec")
    return result


def composition(state: dict):
    date = str(state["ds"])
    book = state["book"]
    equity = number(state["eq"], "core equity", positive=True)
    effective = number(state["eff"]["A"], "effective exposure")
    desired = number(state["a_d"], "close desired exposure")
    require(effective in (0., .55, 1.) and desired in (0., .55, 1.),
            "unexpected champion exposure")
    phase = "MEASUREMENT" if date >= MEASUREMENT_START else "WARMUP"
    rows, positions, tids = [], {}, {}
    lot_ids = []
    for slot in book.slots:
        if not slot.held():
            continue
        tid = int(slot.tid)
        security_id = str(state["sid"][tid])
        require(security_id and tids.get(security_id, tid) == tid,
                "ambiguous permanent identity")
        tids[security_id] = tid
        metadata = state["_metadata"](tid, date)
        require(isinstance(metadata, dict), f"missing PIT metadata: {security_id} {date}")
        ticker = str(metadata.get("ticker", "")).strip()
        effective_date = str(metadata.get("effective_session", ""))
        require(ticker and effective_date and effective_date <= date,
                f"invalid PIT ticker authority: {security_id} {date}")
        require(str(metadata.get("security_id", security_id)) == security_id,
                "metadata identity mismatch")
        mark = float(state["clraw"][tid])
        mark_source = "CURRENT_RAW_CLOSE"
        if not math.isfinite(mark) or mark <= 0:
            mark = book.last_raw.get(tid)
            mark_source = "PRIOR_MARK_CARRIED"
        mark = number(mark, "holding mark", positive=True)
        quantity = number(slot.qty, "holding quantity", positive=True)
        lot_ids.append(security_id)
        if security_id in positions:
            positions[security_id]["quantity"] += quantity
            positions[security_id]["lot_count"] += 1
            positions[security_id]["reference_value"] += quantity * mark
        else:
            positions[security_id] = dict(
                security_id=security_id, ticker=ticker, bucket="STOCK",
                quantity=quantity, lot_count=1, mark=mark, mark_source=mark_source,
                metadata_effective_session=effective_date,
                security_type=str(metadata.get("security_type", "unknown")),
                security_type_source=str(metadata.get("security_type_source", "")),
                reference_value=quantity * mark,
            )
    rows.extend(positions[k] for k in sorted(positions))
    cash = number(book.cash, "Core cash")
    receivables = sum(number(x[1], "receivable") for x in book.receivables)
    stock_value = sum(row["reference_value"] for row in rows)
    require(math.isclose(stock_value + cash + receivables, equity, rel_tol=1e-12, abs_tol=1e-7),
            f"Core equity conservation failed at {date}")
    for bucket, value in (("CORE_CASH", cash), ("DIVIDEND_RECEIVABLE", receivables),
                          ("TBILL_SLEEVE", 0.)):
        rows.append(dict(security_id="", ticker=bucket, bucket=bucket,
                         quantity="", lot_count=0, mark="", mark_source="ACCOUNTING",
                         metadata_effective_session="", security_type="",
                         security_type_source="", reference_value=value))
    for row in rows:
        weight = 100 * row["reference_value"] / equity
        bill = row["bucket"] == "TBILL_SLEEVE"
        row.update(date=date, phase=phase, core_equity=equity, shadow_weight_pct=weight,
                   effective_exposure_pct=100 * effective,
                   effective_model_weight_pct=100 * (1-effective) if bill else weight * effective,
                   close_desired_exposure_pct=100 * desired,
                   next_target_model_weight_pct=100 * (1-desired) if bill else weight * desired)
    sums = [sum(row[key] for row in rows) for key in
            ("shadow_weight_pct", "effective_model_weight_pct", "next_target_model_weight_pct")]
    require(all(math.isclose(x, 100., rel_tol=0, abs_tol=1e-8) for x in sums),
            "portfolio weight conservation failed")
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                                       allow_nan=False).encode()).hexdigest()
    session = dict(date=date, phase=phase, core_equity=equity, stock_value=stock_value,
                   cash=cash, receivables=receivables, stock_count=len(positions),
                   stock_lot_count=len(lot_ids), held_ids_json=json.dumps(sorted(lot_ids)),
                   effective_exposure_pct=100*effective, close_desired_exposure_pct=100*desired,
                   shadow_weight_sum_pct=sums[0], effective_weight_sum_pct=sums[1],
                   next_target_weight_sum_pct=sums[2],
                   carried_mark_count=sum(r["mark_source"] == "PRIOR_MARK_CARRIED" for r in rows),
                   unknown_canonical_type_count=sum(r["security_type"] == "unknown" for r in rows),
                   composition_sha256=digest)
    return rows, session


class Observer:
    def __init__(self, output: Path):
        self.output = output
        self.streams = []
        self.previous_date = None
        self.previous_effective_native = 1.
        self.count = 0
        for name, fields in (("portfolio-composition", FIELDS), ("portfolio-sessions", SESSION_FIELDS),
                             ("observations", OBS_FIELDS)):
            stream = (output / (name + ".csv")).open("x", newline="", encoding="utf-8")
            self.streams.append(stream)
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            setattr(self, name.replace("-", "_"), writer)

    def __call__(self, state):
        date = str(state["ds"])
        require(self.previous_date is None or date > self.previous_date, "duplicate/reordered observation")
        rows, session = composition(state)
        self.portfolio_composition.writerows(rows)
        self.portfolio_sessions.writerow(session)
        ob = {k: state[k] for k in ("dd", "r5", "r10", "r20", "r40", "ddam5", "spy20",
                                    "volacc", "stops20", "open_eq", "recent_r20", "recent_r40")}
        ob.update(date=date, measured=date >= MEASUREMENT_START, dam=state["dam_b"],
                  green=state["green_b"], nav=state["eq"], close_eq=state["eq"],
                  current_native_close_target=state["native_target"],
                  current_effective_native_preclose=self.previous_effective_native,
                  current_close_desired=state["a_d"], current_close_reason=state["a_reason"])
        self.observations.writerow(ob)
        self.previous_date = date
        self.previous_effective_native = float(state["effective_native"])
        self.count += 1
        for stream in self.streams:
            stream.flush()
        if self.count % 126 == 0:
            print(f"[PIT_COMPOSITION] date={date} sessions={self.count} stocks={session['stock_count']} weights=100%", flush=True)

    def close(self):
        for stream in self.streams:
            stream.close()
