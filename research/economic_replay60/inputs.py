"""Research classification assumptions and matched-date performance reporting."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path

START = "2006-07-31"
OVERLAY_SHA256 = "3b8bc54142ff9a06122f11efc8cad012ce1b5262cd8719a50c616fc15a4f2709"


class Classification:
    def __init__(self):
        raw = Path(__file__).with_name("classification-intervals.json.gz").read_bytes()
        if hashlib.sha256(raw).hexdigest() != OVERLAY_SHA256:
            raise ValueError("frozen reference classification input changed")
        doc = json.loads(gzip.decompress(raw))
        self.rows = defaultdict(list)
        for row in doc["intervals"]:
            if row["classification"] not in {"common", "non_common"} or row["first"] > row["last"]:
                raise ValueError("invalid classification interval")
            self.rows[row["security_id"]].append(row)
        for rows in self.rows.values():
            rows.sort(key=lambda r: r["first"])
            if any(a["last"] >= b["first"] for a, b in zip(rows, rows[1:])):
                raise ValueError("overlapping classification intervals")
        if len(self.rows) != doc["security_count"]:
            raise ValueError("classification security count differs")

    def apply(self, row):
        # Match the retained reference policy: known canonical classes take
        # precedence; only unknown classifications use the interval reconstruction.
        if row["security_type"] in {"common", "non_common"}:
            return row
        matches = [r for r in self.rows.get(row["security_id"], ())
                   if r["first"] <= row["session"] <= r["last"]]
        if not matches:
            return row
        match = matches[0]
        if row["ticker"] != match["ticker"]:
            raise ValueError("classification interval ticker/episode mismatch")
        value = match["classification"]
        return {**row, "security_type": value,
                "security_type_eligible": "1" if value == "common" else "0",
                "metadata_admitted": "1" if value == "common" else "0",
                "security_type_source": "RECONSTRUCTED_REFERENCE_ECONOMIC_ASSUMPTION"}


def performance(value, base, start, end):
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    if days < 0:
        raise ValueError("reversed performance period")
    value, base = Decimal(value), Decimal(base)
    if not value.is_finite() or not base.is_finite() or value <= 0 or base <= 0:
        raise ValueError("nonpositive or nonfinite performance NAV")
    multiple = value / base
    cagr = math.expm1(math.log(float(multiple)) * 365.2425 / days) if days else None
    return {"multiple": str(multiple), "cagr": cagr}


def progress(stats, day, nav, refs, spy):
    if day < START:
        return dict(stats), {"date": day, "phase": "FORMATION", "nav": str(nav),
                             "comparison": None}
    result = dict(stats)
    if not result:
        if day != START:
            raise ValueError("measurement baseline is absent")
        result = {"base": str(nav), "reference_base": str(refs[START]),
                  "spy_base": str(spy[START]), "peak": str(nav),
                  "drawdown": "0", "sessions": 0}
    # References and SPY must remain bound to the exact baseline across resumes.
    if Decimal(result["reference_base"]) != refs[START] or Decimal(result["spy_base"]) != spy[START]:
        raise ValueError("benchmark baseline changed")
    result["sessions"] += 1
    value = Decimal(nav)
    result["peak"] = str(max(Decimal(result["peak"]), value))
    result["drawdown"] = str(min(Decimal(result["drawdown"]), value / Decimal(result["peak"]) - 1))
    comparison = {
        "current": performance(nav, result["base"], START, day),
        "reference": performance(refs[day], result["reference_base"], START, day),
        "spy": performance(spy[day], result["spy_base"], START, day)}
    return result, {"date": day, "measurement_start": START,
                    "phase": "PROVISIONAL_MATCHED_DATE_COMPARISON", "nav": str(nav),
                    "maximum_drawdown": result["drawdown"],
                    "comparison": comparison}
