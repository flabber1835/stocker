"""Bounded provider-only collector. No trading/runtime imports or account routes."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as daytime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shlex
import time
from urllib import error, parse, request
from zoneinfo import ZoneInfo

ASSETS = "https://paper-api.alpaca.markets/v2/assets"
BARS = "https://data.alpaca.markets/v2/stocks/bars"
FIGI = "https://api.openfigi.com/v3/mapping"
CONFIG = Path("/home/bron/stocker-local-paper-cold-20261017-90a96054/.env")
ROOT_STATE_SHA = "cde1ea00cfd29b1db761e810758187b8ac2f5e4ea53390c6b07555c300e61544"
ALLOWED_TYPES = {"Common Stock", "ADR", "GDR", "MLP", "Ltd Part", "REIT", "Royalty Trst", "NY Reg Shrs"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    raw = canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return {"bytes": len(raw), "sha256": digest(raw)}


def prepare(state_path, acquisition_path, result_path, protocol_path, output):
    """Export ONLY feed IDs/tickers, never the retained private account state."""
    state_raw = Path(state_path).read_bytes()
    state = json.loads(state_raw)
    acquisition = json.loads(Path(acquisition_path).read_bytes())
    result = json.loads(Path(result_path).read_bytes())
    protocol_raw = Path(protocol_path).read_bytes()
    protocol = json.loads(protocol_raw)
    if digest(canonical(state)) != ROOT_STATE_SHA:
        raise ValueError("REFUSED_RETAINED_STATE_IDENTITY")
    if acquisition["provider"] != "ALPACA_OPENFIGI" or result["diagnostic_result"] != "PASS":
        raise ValueError("REFUSED_COMPLETED_PROVIDER_CAPTURE")
    pairs = []
    for asset_id, series in state["feed"]["series"].items():
        if asset_id != series["security_id"]:
            raise ValueError("REFUSED_ASSET_IDENTITY")
        pairs.append({"asset_id": asset_id, "ticker": series["ticker"]})
    ranked = sorted(pairs, key=lambda row: digest((protocol["cohort_salt"] + row["asset_id"]).encode()))
    selected = ranked[:protocol["cohort_size"]]
    if len({row["ticker"] for row in selected}) != len(selected):
        raise ValueError("REFUSED_DUPLICATE_SELECTED_TICKER")
    evidence = {
        "schema": "research.numerical-forecast-cohort/1", "protocol_sha256": digest(protocol_raw),
        "retained_provider": acquisition["provider"], "retained_capture_result": "PASS",
        "retained_state_file_sha256": digest(state_raw), "retained_state_canonical_sha256": ROOT_STATE_SHA,
        "retained_acquisition_sha256": digest(Path(acquisition_path).read_bytes()),
        "retained_result_sha256": digest(Path(result_path).read_bytes()),
        "selection_before_price_acquisition": True, "source_cohort_size": len(pairs),
        "selected": selected, "financial_state_exported": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save(output, evidence)


def provider_keys(path=CONFIG):
    wanted = {"ALPACA_API_KEY", "ALPACA_SECRET_KEY"}
    keys = {}
    for physical in path.read_text(encoding="utf-8-sig").splitlines():
        line = physical.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and name in wanted:
            tokens = shlex.split(value, comments=True)
            if name in keys or len(tokens) != 1 or not tokens[0] or "$" in tokens[0]:
                raise ValueError("REFUSED_PROVIDER_KEY_FORMAT")
            keys[name] = tokens[0]
    if set(keys) != wanted:
        raise ValueError("REFUSED_PROVIDER_KEYS_UNAVAILABLE")
    return keys


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, output, keys):
        self.output, self.keys = Path(output), keys
        self.opener = request.build_opener(NoRedirect)
        self.started, self.last, self.total = time.monotonic(), {}, 0
        self.receipts = []

    def call(self, endpoint, params=None, body=None):
        if endpoint not in {ASSETS, BARS, FIGI} or (endpoint == FIGI) != (body is not None):
            raise ValueError("REFUSED_ENDPOINT_OR_METHOD")
        if time.monotonic() - self.started > 600:
            raise ValueError("REFUSED_ACQUISITION_TIME_BOUND")
        headers = {"User-Agent": "Stocker-private-forecast-research/1"}
        payload = None
        if endpoint != FIGI:
            headers.update({"APCA-API-KEY-ID": self.keys["ALPACA_API_KEY"],
                            "APCA-API-SECRET-KEY": self.keys["ALPACA_SECRET_KEY"]})
        else:
            payload = canonical(body)
            headers["Content-Type"] = "application/json"
        url = endpoint + ("?" + parse.urlencode(params) if params else "")
        interval = 2.6 if endpoint == FIGI else 0.4
        for attempt in range(3):
            delay = interval - (time.monotonic() - self.last.get(endpoint, 0))
            if delay > 0:
                time.sleep(delay)
            self.last[endpoint] = time.monotonic()
            try:
                with self.opener.open(request.Request(url, data=payload, headers=headers), timeout=25) as response:
                    raw = response.read(32 * 1024 * 1024 + 1)
                if len(raw) > 32 * 1024 * 1024:
                    raise ValueError("REFUSED_RESPONSE_BYTE_BOUND")
                self.total += len(raw)
                if self.total > 96 * 1024 * 1024:
                    raise ValueError("REFUSED_TOTAL_BYTE_BOUND")
                value = json.loads(raw)
                filename = f"provider-{len(self.receipts):03d}.json"
                with (self.output / filename).open("xb") as stream:
                    stream.write(raw)
                self.receipts.append({"file": filename, "endpoint": endpoint, "method": "POST" if body else "GET",
                                      "params": params, "request_body": body, "bytes": len(raw), "sha256": digest(raw),
                                      "observed_at": datetime.now(timezone.utc).isoformat()})
                return value
            except error.HTTPError as exc:
                code = exc.code
                if code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise ValueError(f"PROVIDER_HTTP_{code}") from None
                time.sleep(3 * (attempt + 1))
            except (error.URLError, TimeoutError):
                if attempt == 2:
                    raise ValueError("PROVIDER_NETWORK_FAILURE") from None
                time.sleep(3 * (attempt + 1))
        raise ValueError("REFUSED_REQUEST_EXHAUSTED")


def figi_identity(ticker, reply):
    rows = reply.get("data", []) if isinstance(reply, dict) else []
    facts = set()
    for row in rows:
        if (row.get("marketSector") != "Equity" or row.get("exchCode") != "US"
                or row.get("ticker") != ticker.replace(".", "/")
                or row.get("securityType") not in ALLOWED_TYPES
                or not row.get("compositeFIGI") or not row.get("shareClassFIGI")):
            return None
        facts.add((row["compositeFIGI"], row["shareClassFIGI"], row["securityType"]))
    if len(facts) != 1:
        return None
    composite, share_class, kind = next(iter(facts))
    return {"composite_figi": composite, "share_class_figi": share_class, "security_type": kind}


def collect(cohort_path, protocol_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cohort_raw, protocol_raw = Path(cohort_path).read_bytes(), Path(protocol_path).read_bytes()
    cohort, protocol = json.loads(cohort_raw), json.loads(protocol_raw)
    if cohort["protocol_sha256"] != digest(protocol_raw):
        raise ValueError("REFUSED_COHORT_PROTOCOL")
    client = Client(output, provider_keys())
    status = {"schema": "research.numerical-forecast-acquisition/1", "status": "INCOMPLETE",
              "cohort_sha256": digest(cohort_raw), "protocol_sha256": digest(protocol_raw),
              "production_contacted": False, "broker_account_calls": 0, "providers": ["ALPACA", "OPENFIGI_FREE"]}
    try:
        assets = client.call(ASSETS, {"status": "active", "asset_class": "us_equity"})
        if not isinstance(assets, list):
            raise ValueError("REFUSED_ASSET_RESPONSE")
        by_id = {row["id"]: row for row in assets}
        proposed, excluded = [], []
        for row in cohort["selected"]:
            current = by_id.get(row["asset_id"], {})
            if (current.get("symbol") != row["ticker"] or current.get("status") != "active"
                    or current.get("class") != "us_equity" or current.get("exchange") == "OTC"):
                excluded.append({**row, "reason": "CURRENT_ALPACA_IDENTITY_OR_MEMBERSHIP"})
            else:
                proposed.append(row)
        admitted = []
        for offset in range(0, len(proposed), 10):
            batch = proposed[offset:offset + 10]
            replies = client.call(FIGI, body=[{"idType": "TICKER", "idValue": row["ticker"].replace(".", "/"),
                                             "exchCode": "US", "marketSecDes": "Equity", "includeUnlistedEquities": False}
                                            for row in batch])
            if not isinstance(replies, list) or len(replies) != len(batch):
                raise ValueError("REFUSED_FIGI_BATCH")
            for row, reply in zip(batch, replies):
                identity = figi_identity(row["ticker"], reply)
                if identity is None:
                    excluded.append({**row, "reason": "CURRENT_FIGI_AMBIGUOUS_OR_INELIGIBLE"})
                else:
                    admitted.append({**row, **identity})
        if len(admitted) < protocol["minimum_eligible_series"]:
            raise ValueError("INSUFFICIENT_ELIGIBLE_SERIES")
        if not any(row.get("symbol") == "SPY" and row.get("class") == "us_equity" for row in assets):
            raise ValueError("REFUSED_SPY_CONTEXT_IDENTITY")
        ny = ZoneInfo("America/New_York")
        start = datetime.combine(date.fromisoformat(protocol["start"]), daytime(), ny).isoformat()
        end = datetime.combine(date.fromisoformat(protocol["end"]) + timedelta(days=1), daytime(), ny) - timedelta(microseconds=1)
        symbols = sorted(set([row["ticker"] for row in admitted] + ["SPY"]))
        counts = {}
        for adjustment in protocol["adjustments"]:
            token, seen, total = None, set(), 0
            for page in range(20):
                params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
                          "end": end.isoformat(), "adjustment": adjustment, "feed": protocol["feed"],
                          "asof": protocol["end"], "sort": "asc", "limit": 10000}
                if token is not None:
                    params["page_token"] = token
                reply = client.call(BARS, params)
                if not isinstance(reply.get("bars"), dict):
                    raise ValueError("REFUSED_BAR_RESPONSE")
                total += sum(len(rows) for rows in reply["bars"].values())
                token = reply.get("next_page_token")
                if token is None:
                    break
                if not isinstance(token, str) or token in seen:
                    raise ValueError("REFUSED_PAGINATION")
                seen.add(token)
            else:
                raise ValueError("REFUSED_PAGE_BOUND")
            counts[adjustment] = total
        status.update(status="COMPLETE", admitted=admitted, excluded=excluded, bar_counts=counts,
                      pagination_complete=True)
    except Exception as exc:
        # Never serialize HTTP bodies, credential values, request headers or tracebacks.
        status["failure"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        raise
    finally:
        status.update(provider_receipts=client.receipts, completed_at=datetime.now(timezone.utc).isoformat())
        save(output / "acquisition.json", status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "collect"])
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cohort")
    parser.add_argument("--state")
    parser.add_argument("--acquisition")
    parser.add_argument("--result")
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            prepare(args.state, args.acquisition, args.result, args.protocol, args.output)
        else:
            collect(args.cohort, args.protocol, args.output)
        print(json.dumps({"status": "COMPLETE", "mode": args.mode}))
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
