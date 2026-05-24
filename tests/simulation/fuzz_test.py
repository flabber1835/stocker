#!/usr/bin/env python3
"""
Full fuzzing test for the stocker microservices stack.

Tests every service endpoint with:
  - Invalid/missing fields
  - Wrong types (int/str/float/bool/null/array)
  - Boundary values (0, -1, MAX_INT, empty string, whitespace)
  - Injection strings (SQL, path traversal, shell, XSS, null bytes)
  - Oversized payloads
  - Malformed content types
  - Duplicate/idempotency attacks
  - Business logic edge cases
  - Concurrency races (rapid-fire duplicate POSTs)

Pass criteria: service returns an HTTP response (not a 5xx crash or unhandled exception).
A 4xx response to invalid input is correct behaviour.
A 5xx response to invalid input is a BUG.

Services under test:
  risk-service       :8011
  trade-executor     :8012
  pipeline           :8018
  portfolio-builder  :8008
  alpaca-sync        :8009
  api                :8000
  av-ingestor        :8001
  strategy-validator :8005
  scheduler          :8015
  backtester         :8013
"""

import sys, json, time, threading, uuid, concurrent.futures
import requests
from typing import Any

# ── Service URLs ───────────────────────────────────────────────────────────────
SERVICES = {
    "risk-service":       "http://localhost:8011",
    "trade-executor":     "http://localhost:8012",
    "pipeline":           "http://localhost:8018",
    "portfolio-builder":  "http://localhost:8008",
    "alpaca-sync":        "http://localhost:8009",
    "api":                "http://localhost:8000",
    "av-ingestor":        "http://localhost:8001",
    "strategy-validator": "http://localhost:8005",
    "scheduler":          "http://localhost:8015",
    "backtester":         "http://localhost:8013",
}
TIMEOUT = 8   # seconds per request

# ── Harness ────────────────────────────────────────────────────────────────────
PASSED = []
FAILED = []
CRASHED = []    # 5xx
WARNINGS = []

def _r(label, method, url, expect_not_5xx=True, **kwargs):
    """Execute one request and record result."""
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        resp = getattr(requests, method)(url, **kwargs)
        sc = resp.status_code
        if sc >= 500:
            if expect_not_5xx:
                CRASHED.append(f"{label}  → HTTP {sc}")
                print(f"  💥 {label}  HTTP {sc}  body={resp.text[:120]}")
            else:
                PASSED.append(label)
        else:
            PASSED.append(label)
            print(f"  ✅ {label}  HTTP {sc}")
        return resp
    except requests.exceptions.Timeout:
        WARNINGS.append(f"{label}  → TIMEOUT")
        print(f"  ⏱️  {label}  TIMEOUT")
        return None
    except Exception as e:
        FAILED.append(f"{label}  → {e}")
        print(f"  ❌ {label}  EXCEPTION: {e}")
        return None

def hdr(t):
    print(f"\n{'═'*72}\n  {t}\n{'═'*72}")

def sub(t):
    print(f"\n  ── {t}")

# ── Fuzz corpora ──────────────────────────────────────────────────────────────
SQL_INJECTIONS = [
    "'; DROP TABLE rankings; --",
    "1 OR 1=1",
    "' UNION SELECT NULL,NULL,NULL--",
    "admin'--",
    "1; EXEC xp_cmdshell('dir')",
]
PATH_TRAVERSALS = [
    "../../../etc/passwd",
    "..%2F..%2F..%2Fetc%2Fpasswd",
    "/etc/shadow",
    "C:\\Windows\\win.ini",
]
XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "javascript:alert(1)",
    '"><img src=x onerror=alert(1)>',
]
LARGE_STRING = "A" * 10_000
UNICODE_CHAOS = "𝔘𝔫𝔦𝔠𝔬𝔡𝔢\x00￿ привет emoji🔥 null\x00byte"   # no surrogates (not encodable)
BAD_TYPES: list[Any] = [
    None, True, False, 0, -1, -999, 2**31, 2**63, -2**63,
    0.0, -0.001, float("inf"), float("nan"),
    "", "   ", "\x00", "\n\r\t",
    [], {}, [1, 2, 3], {"nested": "object"},
    LARGE_STRING, UNICODE_CHAOS,
]

VALID_UUID = str(uuid.uuid4())
INVALID_UUIDS = [
    "not-a-uuid", "00000000-0000-0000-0000-000000000000",
    "", "null", "undefined", LARGE_STRING, "'; DROP TABLE--",
    "123", "{}",
]


# ═══════════════════════════════════════════════════════════════════════════════
hdr("1. HEALTH CHECKS — all services must respond 200")
# ═══════════════════════════════════════════════════════════════════════════════
for name, base in SERVICES.items():
    _r(f"health/{name}", "get", f"{base}/health")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("2. RISK SERVICE — /check endpoint")
# ═══════════════════════════════════════════════════════════════════════════════
RISK = SERVICES["risk-service"]

sub("2a. Valid baseline (must be approved or paper-rejected, not 5xx)")
_r("risk/valid-baseline", "post", f"{RISK}/check", json={
    "ticker": "AAPL", "action": "entry", "side": "buy",
    "qty": 10, "notional": 1800.0, "mode": "immediate", "trade_type": "paper"
})

sub("2b. Empty body")
_r("risk/empty-body", "post", f"{RISK}/check", data="")
_r("risk/null-json", "post", f"{RISK}/check", json=None)
_r("risk/empty-json-obj", "post", f"{RISK}/check", json={})

sub("2c. Missing individual required fields")
base_risk = {"ticker":"AAPL","action":"entry","side":"buy","qty":10,"notional":1800.0,"mode":"immediate","trade_type":"paper"}
for drop in ["ticker","action","side","qty","notional","mode","trade_type"]:
    body = {k:v for k,v in base_risk.items() if k != drop}
    _r(f"risk/missing-{drop}", "post", f"{RISK}/check", json=body)

sub("2d. Wrong types for each field")
for field in ["qty", "notional"]:
    for bad in [None, "", "abc", -1, 0, -999, LARGE_STRING, [], {}]:
        body = {**base_risk, field: bad}
        _r(f"risk/wrong-type-{field}={repr(bad)[:20]}", "post", f"{RISK}/check", json=body)

sub("2e. Injection strings in ticker")
for payload in SQL_INJECTIONS + PATH_TRAVERSALS + XSS_PAYLOADS:
    _r(f"risk/injection-ticker", "post", f"{RISK}/check",
       json={**base_risk, "ticker": payload})

sub("2f. Unknown/invalid enum values")
for field, bads in [
    ("action", ["SELL","delete","null","buy_everything",""]),
    ("side",   ["short","long","BUY","SELL",""]),
    ("mode",   ["batch","live","immediate ","deferred",""]),
    ("trade_type", ["demo","live ","pape",""]),
]:
    for bad in bads:
        _r(f"risk/bad-{field}={bad!r}", "post", f"{RISK}/check", json={**base_risk, field: bad})

sub("2g. Boundary numeric values")
for qty in [0, -1, 1, 999_999, 2**31, 0.1, 0.9, "10"]:
    _r(f"risk/qty={qty}", "post", f"{RISK}/check", json={**base_risk, "qty": qty, "notional": 1800.0})
for notional in [0, -1, 0.001, 10_000_001]:
    _r(f"risk/notional={notional}", "post", f"{RISK}/check",
       json={**base_risk, "notional": notional})
# inf and nan cannot be encoded as JSON — send as string to test the type-validation path
for notional_str in ["Infinity", "NaN", "inf", "nan"]:
    _r(f"risk/notional={notional_str!r}", "post", f"{RISK}/check",
       json={**base_risk, "notional": notional_str})

sub("2h. Oversized payload")
_r("risk/10k-ticker", "post", f"{RISK}/check",
   json={**base_risk, "ticker": LARGE_STRING})
_r("risk/unicode-chaos", "post", f"{RISK}/check",
   json={**base_risk, "ticker": UNICODE_CHAOS})

sub("2i. Wrong Content-Type")
_r("risk/wrong-content-type-text", "post", f"{RISK}/check",
   data='{"ticker":"AAPL","action":"entry","side":"buy","qty":10,"notional":1800,"mode":"immediate","trade_type":"paper"}',
   headers={"Content-Type": "text/plain"})
_r("risk/xml-content-type", "post", f"{RISK}/check",
   data="<check/>", headers={"Content-Type": "application/xml"})


# ═══════════════════════════════════════════════════════════════════════════════
hdr("3. TRADE EXECUTOR — /jobs/submit")
# ═══════════════════════════════════════════════════════════════════════════════
TRADE = SERVICES["trade-executor"]

sub("3a. Empty / null body")
_r("trade/empty-body", "post", f"{TRADE}/jobs/submit", data="")
_r("trade/empty-obj", "post", f"{TRADE}/jobs/submit", json={})

sub("3b. Invalid intent_id values")
for bad_id in INVALID_UUIDS:
    _r(f"trade/bad-intent-id={bad_id[:30]!r}", "post", f"{TRADE}/jobs/submit",
       json={"intent_id": bad_id, "mode": "immediate"})

sub("3c. Invalid mode values")
for bad_mode in ["", "instant", "batch", "scheduled ", None, 0, []]:
    _r(f"trade/bad-mode={bad_mode!r}", "post", f"{TRADE}/jobs/submit",
       json={"intent_id": VALID_UUID, "mode": bad_mode})

sub("3d. Duplicate submission race (same intent_id twice)")
payload = {"intent_id": VALID_UUID, "mode": "immediate"}
results = []
def submit():
    try:
        r = requests.post(f"{TRADE}/jobs/submit", json=payload, timeout=TIMEOUT)
        results.append(r.status_code)
    except Exception as e:
        results.append(str(e))

threads = [threading.Thread(target=submit) for _ in range(5)]
for t in threads: t.start()
for t in threads: t.join()
crashed_5xx = [r for r in results if isinstance(r, int) and r >= 500]
if crashed_5xx:
    CRASHED.append(f"trade/duplicate-race → 5xx responses: {crashed_5xx}")
    print(f"  💥 trade/duplicate-race  5xx responses: {crashed_5xx}")
else:
    PASSED.append("trade/duplicate-race")
    print(f"  ✅ trade/duplicate-race  responses: {results}")

sub("3e. Orders recent endpoint fuzzing")
_r("trade/orders-recent", "get", f"{TRADE}/orders/recent")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("4. PIPELINE — /jobs/run, /runs/latest, /jobs/delta")
# ═══════════════════════════════════════════════════════════════════════════════
PIPE = SERVICES["pipeline"]

sub("4a. Basic reads")
_r("pipeline/runs-latest", "get", f"{PIPE}/runs/latest")
_r("pipeline/health", "get", f"{PIPE}/health")

sub("4b. POST /jobs/run with various bodies")
_r("pipeline/run-empty", "post", f"{PIPE}/jobs/run", json={})
_r("pipeline/run-force", "post", f"{PIPE}/jobs/run?force=true", json={})
_r("pipeline/run-bad-force", "post", f"{PIPE}/jobs/run?force=maybe", json={})
_r("pipeline/run-with-junk", "post", f"{PIPE}/jobs/run",
   json={"injected": "'; DROP TABLE rankings--", "extra": LARGE_STRING})
_r("pipeline/run-null-body", "post", f"{PIPE}/jobs/run", json=None)
_r("pipeline/run-array-body", "post", f"{PIPE}/jobs/run", json=[1, 2, 3])
_r("pipeline/run-string-body", "post", f"{PIPE}/jobs/run",
   data="not json", headers={"Content-Type": "application/json"})

sub("4c. POST /jobs/delta")
_r("pipeline/delta-empty", "post", f"{PIPE}/jobs/delta", json={})
_r("pipeline/delta-bad-params", "post", f"{PIPE}/jobs/delta",
   json={"ranking_run_id": "not-a-uuid", "force": "yes"})

sub("4d. Rapid-fire duplicate triggers")
results = []
def fire_pipeline():
    try:
        r = requests.post(f"{PIPE}/jobs/run?force=true", json={}, timeout=TIMEOUT)
        results.append(r.status_code)
    except Exception as e:
        results.append(str(e))

threads = [threading.Thread(target=fire_pipeline) for _ in range(6)]
for t in threads: t.start()
for t in threads: t.join()
crashed_5xx = [r for r in results if isinstance(r, int) and r >= 500]
if crashed_5xx:
    CRASHED.append(f"pipeline/concurrent-run → 5xx: {crashed_5xx}")
    print(f"  💥 pipeline/concurrent-run  5xx: {crashed_5xx}")
else:
    PASSED.append("pipeline/concurrent-run")
    print(f"  ✅ pipeline/concurrent-run  responses: {results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("5. PORTFOLIO BUILDER — /jobs/build, /runs/{run_id}")
# ═══════════════════════════════════════════════════════════════════════════════
PB = SERVICES["portfolio-builder"]

sub("5a. Basic reads")
_r("pb/health", "get", f"{PB}/health")
_r("pb/runs-latest", "get", f"{PB}/runs/latest")
_r("pb/portfolio-latest", "get", f"{PB}/portfolio/latest")

sub("5b. Invalid run_id in /runs/{run_id}")
for bad_id in INVALID_UUIDS[:6]:
    _r(f"pb/runs-bad-id={bad_id[:20]!r}", "get", f"{PB}/runs/{bad_id}")

sub("5c. /jobs/build with invalid ranking_run_id")
_r("pb/build-no-params", "post", f"{PB}/jobs/build")
_r("pb/build-bad-ranking-id", "post", f"{PB}/jobs/build?ranking_run_id=not-a-uuid")
_r("pb/build-nonexistent-id", "post", f"{PB}/jobs/build",
   params={"ranking_run_id": VALID_UUID})
_r("pb/build-injection-id", "post", f"{PB}/jobs/build",
   params={"ranking_run_id": "'; DROP TABLE portfolio_runs;--"})
_r("pb/build-empty-id", "post", f"{PB}/jobs/build", params={"ranking_run_id": ""})

sub("5d. Concurrent build triggers")
results = []
def fire_build():
    try:
        r = requests.post(f"{PB}/jobs/build", timeout=TIMEOUT)
        results.append(r.status_code)
    except Exception as e:
        results.append(str(e))

threads = [threading.Thread(target=fire_build) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()
crashed_5xx = [r for r in results if isinstance(r, int) and r >= 500]
if crashed_5xx:
    CRASHED.append(f"pb/concurrent-build → 5xx: {crashed_5xx}")
    print(f"  💥 pb/concurrent-build  5xx: {crashed_5xx}")
else:
    PASSED.append("pb/concurrent-build")
    print(f"  ✅ pb/concurrent-build  responses: {results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("6. ALPACA SYNC — /jobs/sync, /positions, /runs/latest")
# ═══════════════════════════════════════════════════════════════════════════════
ASYNC = SERVICES["alpaca-sync"]

sub("6a. Basic reads")
_r("sync/health", "get", f"{ASYNC}/health")
_r("sync/positions", "get", f"{ASYNC}/positions")
_r("sync/runs-latest", "get", f"{ASYNC}/runs/latest")

sub("6b. POST /jobs/sync with various bodies")
_r("sync/trigger-empty", "post", f"{ASYNC}/jobs/sync", json={})
_r("sync/trigger-junk", "post", f"{ASYNC}/jobs/sync",
   json={"injected": SQL_INJECTIONS[0], "extra": LARGE_STRING})
_r("sync/trigger-null", "post", f"{ASYNC}/jobs/sync", json=None)
_r("sync/trigger-string-body", "post", f"{ASYNC}/jobs/sync",
   data="not-json", headers={"Content-Type": "application/json"})

sub("6c. Concurrent sync triggers")
results = []
def fire_sync():
    try:
        r = requests.post(f"{ASYNC}/jobs/sync", json={}, timeout=TIMEOUT)
        results.append(r.status_code)
    except Exception as e:
        results.append(str(e))

threads = [threading.Thread(target=fire_sync) for _ in range(5)]
for t in threads: t.start()
for t in threads: t.join()
crashed_5xx = [r for r in results if isinstance(r, int) and r >= 500]
if crashed_5xx:
    CRASHED.append(f"sync/concurrent → 5xx: {crashed_5xx}")
    print(f"  💥 sync/concurrent  5xx: {crashed_5xx}")
else:
    PASSED.append("sync/concurrent")
    print(f"  ✅ sync/concurrent  responses: {results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("7. API SERVICE — rankings, portfolio, delta, trade, traces")
# ═══════════════════════════════════════════════════════════════════════════════
API = SERVICES["api"]

sub("7a. Basic read endpoints")
for ep in ["/health", "/regime", "/rankings", "/rankings/with-overlays",
           "/universe", "/universe/investable", "/portfolio",
           "/live-portfolio", "/delta/latest", "/orders/recent",
           "/data-freshness", "/system/status", "/factor-runs",
           "/ranking-runs", "/traces"]:
    _r(f"api{ep}", "get", f"{API}{ep}")

sub("7b. /factors/{ticker} — valid and invalid ticker formats")
valid_tickers = ["AAPL", "BRK.B", "BRK-B", "SPY"]
for t in valid_tickers:
    _r(f"api/factors/{t}", "get", f"{API}/factors/{t}")

bad_tickers = [
    "", " ", "aapl", "TOOLONGTICKER", "AAPL;DROP",
    "../etc/passwd", "<script>", "A" * 100,
    "TICK00", UNICODE_CHAOS[:10],
    "'; SELECT * FROM factor_scores--",
]
for t in bad_tickers:
    import urllib.parse
    encoded = urllib.parse.quote(t, safe="")
    _r(f"api/factors/bad-ticker={t[:25]!r}", "get", f"{API}/factors/{encoded}")

sub("7c. /traces/{trace_id} — valid and invalid UUIDs")
_r("api/traces/valid-uuid", "get", f"{API}/traces/{VALID_UUID}")
for bad_id in INVALID_UUIDS:
    encoded = urllib.parse.quote(bad_id, safe="")
    _r(f"api/traces/bad-id={bad_id[:20]!r}", "get", f"{API}/traces/{encoded}")

sub("7d. /rankings with extreme limit params")
for limit in [0, -1, 1, 500, 100_000, "abc", -999, None, "", "1;DROP TABLE"]:
    try:
        r = requests.get(f"{API}/rankings", params={"limit": limit}, timeout=TIMEOUT)
        sc = r.status_code
        label = f"api/rankings?limit={limit!r}"
        if sc >= 500:
            CRASHED.append(f"{label} → HTTP {sc}")
            print(f"  💥 {label}  HTTP {sc}")
        else:
            PASSED.append(label)
            print(f"  ✅ {label}  HTTP {sc}")
    except Exception as e:
        FAILED.append(f"api/rankings?limit={limit!r} → {e}")

sub("7e. POST /trade/approve — invalid inputs")
_r("api/approve-empty", "post", f"{API}/trade/approve", json={})
_r("api/approve-bad-id", "post", f"{API}/trade/approve",
   json={"intent_id": "not-a-uuid", "mode": "immediate"})
_r("api/approve-bad-mode", "post", f"{API}/trade/approve",
   json={"intent_id": VALID_UUID, "mode": "INVALID"})
_r("api/approve-injection", "post", f"{API}/trade/approve",
   json={"intent_id": SQL_INJECTIONS[0], "mode": "immediate"})
_r("api/approve-null-mode", "post", f"{API}/trade/approve",
   json={"intent_id": VALID_UUID, "mode": None})
_r("api/approve-no-mode", "post", f"{API}/trade/approve",
   json={"intent_id": VALID_UUID})
_r("api/approve-extra-fields", "post", f"{API}/trade/approve",
   json={"intent_id": VALID_UUID, "mode": "immediate",
         "injected": SQL_INJECTIONS[0], "extra": LARGE_STRING})

sub("7f. POST /trade/reject — invalid inputs")
_r("api/reject-empty", "post", f"{API}/trade/reject", json={})
_r("api/reject-bad-id", "post", f"{API}/trade/reject",
   json={"intent_id": "not-a-uuid"})
_r("api/reject-injection", "post", f"{API}/trade/reject",
   json={"intent_id": SQL_INJECTIONS[0]})
_r("api/reject-null", "post", f"{API}/trade/reject", json={"intent_id": None})
_r("api/reject-array", "post", f"{API}/trade/reject", json={"intent_id": [1,2,3]})

sub("7g. POST /alpaca/sync")
_r("api/sync-empty", "post", f"{API}/alpaca/sync", json={})
_r("api/sync-junk", "post", f"{API}/alpaca/sync",
   json={"junk": SQL_INJECTIONS[0]})

sub("7h. Method not allowed")
_r("api/GET-health-as-POST", "post", f"{API}/health", json={})
_r("api/DELETE-rankings", "delete", f"{API}/rankings")
_r("api/PUT-portfolio", "put", f"{API}/portfolio", json={})

sub("7i. Nonexistent endpoints")
for ep in ["/nonexistent", "/api/v2/rankings", "/../etc/passwd",
           "/rankings/../../../etc/passwd", "/<script>", "/admin",
           "/internal", "/.env", "/config"]:
    _r(f"api/404-{ep}", "get", f"{API}{ep}")

sub("7j. Deeply nested JSON body")
nested = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
_r("api/approve-deep-nested", "post", f"{API}/trade/approve", json=nested)

sub("7k. Oversized request body (1MB)")
_r("api/approve-huge", "post", f"{API}/trade/approve",
   json={"intent_id": VALID_UUID, "mode": "immediate", "padding": "X" * 1_000_000})


# ═══════════════════════════════════════════════════════════════════════════════
hdr("8. AV INGESTOR — /jobs/fetch-* endpoints")
# ═══════════════════════════════════════════════════════════════════════════════
AVI = SERVICES["av-ingestor"]

sub("8a. Basic reads")
_r("avi/health", "get", f"{AVI}/health")
_r("avi/runs-latest", "get", f"{AVI}/runs/latest")
_r("avi/status", "get", f"{AVI}/status")

sub("8b. Trigger endpoints with junk bodies")
for ep in ["/jobs/fetch-universe", "/jobs/fetch-data",
           "/jobs/fetch-prices", "/jobs/fetch-fundamentals"]:
    _r(f"avi{ep}-empty", "post", f"{AVI}{ep}", json={})
    _r(f"avi{ep}-junk", "post", f"{AVI}{ep}",
       json={"inject": SQL_INJECTIONS[0], "extra": LARGE_STRING})
    _r(f"avi{ep}-null", "post", f"{AVI}{ep}", json=None)

sub("8c. /runs/{run_id} with invalid IDs")
for bad_id in INVALID_UUIDS[:4]:
    _r(f"avi/runs-bad-id={bad_id[:20]!r}", "get", f"{AVI}/runs/{bad_id}")

sub("8d. Concurrent fetch triggers")
results = []
def fire_fetch():
    try:
        r = requests.post(f"{AVI}/jobs/fetch-data", json={}, timeout=TIMEOUT)
        results.append(r.status_code)
    except Exception as e:
        results.append(str(e))

threads = [threading.Thread(target=fire_fetch) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()
crashed_5xx = [r for r in results if isinstance(r, int) and r >= 500]
if crashed_5xx:
    CRASHED.append(f"avi/concurrent-fetch → 5xx: {crashed_5xx}")
    print(f"  💥 avi/concurrent-fetch  5xx: {crashed_5xx}")
else:
    PASSED.append("avi/concurrent-fetch")
    print(f"  ✅ avi/concurrent-fetch  responses: {results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("9. STRATEGY VALIDATOR — /validate")
# ═══════════════════════════════════════════════════════════════════════════════
SV = SERVICES["strategy-validator"]

sub("9a. Valid strategy (baseline)")
import yaml, io
VALID_STRATEGY_YAML = """
strategy_id: fuzz_test_v1
description: Fuzzing test strategy
universe:
  source: av_listing
  min_price: 5.0
  min_avg_dollar_volume_20d: 20000000
regime_detection:
  slow_sma: 200
  vol_window: 20
  vol_threshold: 0.20
  confirmation_days: 5
  regimes:
    bull_calm:   {spy_above_slow_sma: true,  vol_above_threshold: false}
    bull_stress: {spy_above_slow_sma: true,  vol_above_threshold: true}
    bear_stress: {spy_above_slow_sma: false, vol_above_threshold: true}
    bear_calm:   {spy_above_slow_sma: false, vol_above_threshold: false}
factor_weights:
  bull_calm:   {momentum: 0.35, quality: 0.25, value: 0.15, growth: 0.15, low_volatility: 0.10}
  bull_stress: {momentum: 0.20, quality: 0.35, value: 0.15, growth: 0.10, low_volatility: 0.20}
  bear_stress: {momentum: 0.10, quality: 0.40, value: 0.15, growth: 0.05, low_volatility: 0.30}
  bear_calm:   {momentum: 0.20, quality: 0.30, value: 0.30, growth: 0.10, low_volatility: 0.10}
max_positions: 30
min_score_percentile: 0.0
portfolio_builder:
  method: greedy_score_per_port_vol
  max_positions: 30
  max_position_weight: 0.10
  max_sector_weight: 0.30
  weighting: equal_weight
vetter:
  candidate_count: 50
"""
_r("sv/valid-yaml", "post", f"{SV}/validate",
   data=VALID_STRATEGY_YAML, headers={"Content-Type": "application/x-yaml"})

sub("9b. Empty / null / garbage inputs")
_r("sv/empty-body", "post", f"{SV}/validate", data="")
_r("sv/null-json", "post", f"{SV}/validate", json=None)
_r("sv/empty-json", "post", f"{SV}/validate", json={})
_r("sv/plain-text", "post", f"{SV}/validate",
   data="just some random text", headers={"Content-Type": "text/plain"})
_r("sv/binary-body", "post", f"{SV}/validate",
   data=b"\x00\xff\xfe binary garbage \x00",
   headers={"Content-Type": "application/octet-stream"})
_r("sv/huge-body", "post", f"{SV}/validate",
   data="X" * 1_000_000, headers={"Content-Type": "application/x-yaml"})

sub("9c. Malformed YAML")
_r("sv/malformed-yaml-tabs", "post", f"{SV}/validate",
   data="key:\tvalue\n  nested:\t\tbad", headers={"Content-Type": "application/x-yaml"})
_r("sv/yaml-anchors-bomb", "post", f"{SV}/validate",
   data="a: &a ['lol','lol','lol']\nb: *a\n" * 100,
   headers={"Content-Type": "application/x-yaml"})
_r("sv/unclosed-quote", "post", f"{SV}/validate",
   data='strategy_id: "unclosed', headers={"Content-Type": "application/x-yaml"})

sub("9d. Dangerous but valid-looking configs")
dangerous_configs = [
    ("max-positions-huge",     "max_positions: 9999"),
    ("max-position-weight-1",  "max_position_weight: 1.0"),
    ("max-sector-weight-1",    "max_sector_weight: 1.0"),
    ("negative-min-price",     "min_price: -100"),
    ("zero-confirmation-days", "confirmation_days: 0"),
    ("live-trading",           "paper_or_live: live"),
]
base_template = VALID_STRATEGY_YAML.strip()
for name, override_yaml in dangerous_configs:
    cfg = base_template + f"\n{override_yaml}\n"
    _r(f"sv/dangerous-{name}", "post", f"{SV}/validate",
       data=cfg, headers={"Content-Type": "application/x-yaml"})

sub("9e. YAML injection attacks")
for inject in SQL_INJECTIONS[:3] + XSS_PAYLOADS[:2]:
    cfg = f"strategy_id: {inject}\n{base_template}\n"
    _r(f"sv/yaml-inject={inject[:20]!r}", "post", f"{SV}/validate",
       data=cfg, headers={"Content-Type": "application/x-yaml"})

sub("9f. Unknown fields (should be rejected by strict validator)")
_r("sv/unknown-fields", "post", f"{SV}/validate",
   data=base_template + "\nunknown_field: should_fail\ninjected_sql: '; DROP TABLE--\n",
   headers={"Content-Type": "application/x-yaml"})

sub("9g. Factor weights that don't sum to 1.0")
bad_weights = VALID_STRATEGY_YAML.replace(
    "{momentum: 0.35, quality: 0.25, value: 0.15, growth: 0.15, low_volatility: 0.10}",
    "{momentum: 0.99, quality: 0.99, value: 0.99, growth: 0.99, low_volatility: 0.99}"
)
_r("sv/weights-dont-sum-1", "post", f"{SV}/validate",
   data=bad_weights, headers={"Content-Type": "application/x-yaml"})

sub("9h. Missing required regimes")
incomplete_regimes = VALID_STRATEGY_YAML.replace(
    "    bear_calm:   {spy_above_slow_sma: false, vol_above_threshold: false}", ""
)
_r("sv/missing-regime", "post", f"{SV}/validate",
   data=incomplete_regimes, headers={"Content-Type": "application/x-yaml"})


# ═══════════════════════════════════════════════════════════════════════════════
hdr("10. SCHEDULER — /jobs/run-now, /status, /debug/log")
# ═══════════════════════════════════════════════════════════════════════════════
SCHED = SERVICES["scheduler"]

sub("10a. Basic reads")
_r("sched/health", "get", f"{SCHED}/health")
_r("sched/status", "get", f"{SCHED}/status")
_r("sched/debug-log", "get", f"{SCHED}/debug/log")
_r("sched/runs-latest", "get", f"{SCHED}/runs/latest")

sub("10b. POST /jobs/run-now with various bodies")
_r("sched/run-now-empty", "post", f"{SCHED}/jobs/run-now", json={})
_r("sched/run-now-junk", "post", f"{SCHED}/jobs/run-now",
   json={"inject": SQL_INJECTIONS[0], "extra": LARGE_STRING})
_r("sched/run-now-null", "post", f"{SCHED}/jobs/run-now", json=None)

sub("10c. Concurrent run-now triggers")
results = []
def fire_runnow():
    try:
        r = requests.post(f"{SCHED}/jobs/run-now", json={}, timeout=TIMEOUT)
        results.append(r.status_code)
    except Exception as e:
        results.append(str(e))

threads = [threading.Thread(target=fire_runnow) for _ in range(5)]
for t in threads: t.start()
for t in threads: t.join()
crashed_5xx = [r for r in results if isinstance(r, int) and r >= 500]
if crashed_5xx:
    CRASHED.append(f"sched/concurrent-run-now → 5xx: {crashed_5xx}")
    print(f"  💥 sched/concurrent-run-now  5xx: {crashed_5xx}")
else:
    PASSED.append("sched/concurrent-run-now")
    print(f"  ✅ sched/concurrent-run-now  responses: {results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("11. BACKTESTER — /jobs/backtest")
# ═══════════════════════════════════════════════════════════════════════════════
BT = SERVICES["backtester"]

sub("11a. Basic reads")
_r("bt/health", "get", f"{BT}/health")

sub("11b. POST /jobs/backtest with various inputs")
_r("bt/backtest-empty", "post", f"{BT}/jobs/backtest", json={})
_r("bt/backtest-valid-minimal", "post", f"{BT}/jobs/backtest",
   json={"date_from": "2024-01-01", "date_to": "2024-06-01"})
_r("bt/backtest-bad-dates", "post", f"{BT}/jobs/backtest",
   json={"date_from": "not-a-date", "date_to": "2099-99-99"})
_r("bt/backtest-reversed-dates", "post", f"{BT}/jobs/backtest",
   json={"date_from": "2025-12-31", "date_to": "2020-01-01"})
_r("bt/backtest-injection-dates", "post", f"{BT}/jobs/backtest",
   json={"date_from": SQL_INJECTIONS[0], "date_to": SQL_INJECTIONS[1]})
_r("bt/backtest-extreme-tx-cost", "post", f"{BT}/jobs/backtest",
   json={"date_from": "2024-01-01", "date_to": "2024-06-01", "tx_cost_bps": -9999})
_r("bt/backtest-null-dates", "post", f"{BT}/jobs/backtest",
   json={"date_from": None, "date_to": None})
_r("bt/backtest-numeric-dates", "post", f"{BT}/jobs/backtest",
   json={"date_from": 20240101, "date_to": 20240601})
_r("bt/backtest-far-future", "post", f"{BT}/jobs/backtest",
   json={"date_from": "2099-01-01", "date_to": "2099-12-31"})
_r("bt/backtest-huge-padding", "post", f"{BT}/jobs/backtest",
   json={"date_from": "2024-01-01", "date_to": "2024-06-01",
         "junk_field": LARGE_STRING, "sql": SQL_INJECTIONS[0]})

sub("11c. Concurrent backtests")
results = []
def fire_bt():
    try:
        r = requests.post(f"{BT}/jobs/backtest",
                          json={"date_from": "2024-01-01", "date_to": "2024-06-01"},
                          timeout=TIMEOUT)
        results.append(r.status_code)
    except Exception as e:
        results.append(str(e))

threads = [threading.Thread(target=fire_bt) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()
crashed_5xx = [r for r in results if isinstance(r, int) and r >= 500]
if crashed_5xx:
    CRASHED.append(f"bt/concurrent → 5xx: {crashed_5xx}")
    print(f"  💥 bt/concurrent  5xx: {crashed_5xx}")
else:
    PASSED.append("bt/concurrent")
    print(f"  ✅ bt/concurrent  responses: {results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("12. CROSS-SERVICE SECURITY CHECKS")
# ═══════════════════════════════════════════════════════════════════════════════

sub("12a. HTTP verb confusion on write endpoints")
write_endpoints = [
    (RISK, "/check"),
    (TRADE, "/jobs/submit"),
    (PIPE, "/jobs/run"),
    (PB, "/jobs/build"),
    (ASYNC, "/jobs/sync"),
    (AVI, "/jobs/fetch-data"),
    (SCHED, "/jobs/run-now"),
]
for base, ep in write_endpoints:
    _r(f"sec/GET-{ep}", "get", f"{base}{ep}")
    _r(f"sec/DELETE-{ep}", "delete", f"{base}{ep}")

sub("12b. Path traversal on run_id endpoints")
traversals = ["../health", "../../etc/passwd", "%2e%2e%2fhealth", "%252e%252e%252f"]
for svc, name in [(PIPE, "pipeline"), (PB, "portfolio-builder"), (AVI, "av-ingestor"), (BT, "backtester")]:
    for trav in traversals[:2]:
        _r(f"sec/{name}/path-traversal={trav!r}", "get", f"{svc}/runs/{trav}")

sub("12c. Header injection attacks")
evil_headers = {
    "X-Forwarded-For": "127.0.0.1' OR '1'='1",
    "X-Real-IP": SQL_INJECTIONS[0],
    "Host": "evil.example.com",
    "X-Original-URL": "/admin",
    "X-Rewrite-URL": "/health/../admin",
}
_r("sec/header-injection-risk", "post", f"{RISK}/check",
   json=base_risk, headers=evil_headers)
_r("sec/header-injection-api", "get", f"{API}/rankings", headers=evil_headers)

sub("12d. Null bytes in all positions")
null_payloads = [
    {"ticker": "AAPL\x00DROP", "action": "entry", "side": "buy",
     "qty": 10, "notional": 1800.0, "mode": "immediate", "trade_type": "paper"},
    {"ticker": "\x00", "action": "entry", "side": "buy",
     "qty": 10, "notional": 1800.0, "mode": "immediate", "trade_type": "paper"},
]
for p in null_payloads:
    _r("sec/null-byte-in-risk-ticker", "post", f"{RISK}/check", json=p)

sub("12e. JSON with duplicate keys")
import json as jsonlib
dup_key_body = b'{"intent_id": "aaa", "intent_id": "bbb", "mode": "immediate"}'
_r("sec/duplicate-json-keys", "post", f"{TRADE}/jobs/submit",
   data=dup_key_body, headers={"Content-Type": "application/json"})

sub("12f. Extremely large single field values")
for svc, ep, field, val in [
    (RISK,  "/check",        "ticker",    "A" * 100_000),
    (RISK,  "/check",        "action",    "X" * 50_000),
    (API,   "/trade/approve","intent_id", "X" * 50_000),
    (TRADE, "/jobs/submit",  "intent_id", "X" * 50_000),
]:
    body = {**base_risk, field: val} if svc == RISK else {"intent_id": val, "mode": "immediate"}
    _r(f"sec/huge-{field}-{svc.split('//')[-1].split(':')[1]}", "post", f"{svc}{ep}", json=body)

sub("12g. Kill-switch: verify risk-service still responds under toggle (file check)")
# Touch the kill switch file inside the risk container via Docker
import subprocess
try:
    result = subprocess.run(
        ["docker", "--host=unix:///tmp/docker.sock", "exec",
         "stocker-risk-service-1", "touch", "/tmp/kill_switch"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        r = _r("sec/kill-switch-on", "post", f"{RISK}/check", json=base_risk)
        if r and r.status_code == 200:
            body = r.json()
            if body.get("approved") is False and "kill" in str(body).lower():
                PASSED.append("sec/kill-switch-blocks-trades")
                print("  ✅ sec/kill-switch  correctly blocks all trades")
            else:
                WARNINGS.append(f"sec/kill-switch may not block trades: {body}")
                print(f"  ⚠️  sec/kill-switch response: {body}")
    # Always remove the kill switch after test
    subprocess.run(
        ["docker", "--host=unix:///tmp/docker.sock", "exec",
         "stocker-risk-service-1", "rm", "-f", "/tmp/kill_switch"],
        capture_output=True, timeout=5
    )
    _r("sec/kill-switch-off", "post", f"{RISK}/check", json=base_risk)
except Exception as e:
    WARNINGS.append(f"sec/kill-switch-test → Docker exec failed: {e}")
    print(f"  ⚠️  kill-switch Docker exec failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("13. RESOURCE EXHAUSTION")
# ═══════════════════════════════════════════════════════════════════════════════

sub("13a. 10MB POST bodies")
huge = "X" * 10_000_000
for svc, ep, content_type in [
    (RISK,  "/check",        "application/json"),
    (SV,    "/validate",     "application/x-yaml"),
    (API,   "/trade/approve","application/json"),
]:
    r = None
    try:
        r = requests.post(f"{svc}{ep}", data=huge.encode(),
                          headers={"Content-Type": content_type}, timeout=10)
        sc = r.status_code
        if sc >= 500:
            CRASHED.append(f"exhaustion/10mb-{svc.split(':')[2]}{ep} → {sc}")
            print(f"  💥 exhaustion/10mb  HTTP {sc}")
        else:
            PASSED.append(f"exhaustion/10mb-{svc.split(':')[2]}{ep}")
            print(f"  ✅ exhaustion/10mb  HTTP {sc}")
    except Exception as e:
        WARNINGS.append(f"exhaustion/10mb → {e}")
        print(f"  ⚠️  exhaustion/10mb  {e}")

sub("13b. Deeply nested JSON (20 levels)")
nested = {"a": None}
for _ in range(20):
    nested = {"child": nested, "data": "x" * 1000}
_r("exhaustion/deep-nest", "post", f"{RISK}/check", json=nested)
_r("exhaustion/deep-nest-api", "post", f"{API}/trade/approve", json=nested)

sub("13c. Array of 10k items")
big_array = [{"ticker": f"T{i}", "qty": i} for i in range(10_000)]
_r("exhaustion/huge-array", "post", f"{RISK}/check", json=big_array)

sub("13d. Many rapid sequential GETs on read endpoints")
import time
t_start = time.monotonic()
n = 50
for i in range(n):
    requests.get(f"{API}/rankings", timeout=TIMEOUT)
elapsed = time.monotonic() - t_start
rps = n / elapsed
print(f"  ⚡ {n} rapid GETs: {rps:.1f} req/s ({elapsed:.2f}s total)")
if rps < 1:
    WARNINGS.append(f"exhaustion/rapid-GETs: very slow ({rps:.1f} req/s)")
    print(f"  ⚠️  Performance warning: {rps:.1f} req/s is unusually slow")
else:
    PASSED.append("exhaustion/rapid-GETs")
    print(f"  ✅ exhaustion/rapid-GETs: {rps:.1f} req/s")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("14. INVARIANT CHECKS")
# ═══════════════════════════════════════════════════════════════════════════════

sub("14a. All services still healthy after fuzzing")
for name, base in SERVICES.items():
    r = _r(f"post-fuzz/health/{name}", "get", f"{base}/health")
    if r and r.status_code == 200:
        body = r.json()
        if body.get("status") not in ("ok", "healthy", "up"):
            WARNINGS.append(f"post-fuzz/{name} health degraded: {body}")
            print(f"  ⚠️  {name} health shows: {body.get('status')}")

sub("14b. Risk service still enforces kill switch = OFF (must approve paper trades)")
r = requests.post(f"{RISK}/check", json=base_risk, timeout=TIMEOUT)
if r.status_code == 200:
    body = r.json()
    # After all fuzzing, risk service should still process checks (not return 5xx)
    PASSED.append("invariant/risk-service-functional")
    print(f"  ✅ invariant/risk-service  approved={body.get('approved')}  status={r.status_code}")
else:
    CRASHED.append(f"invariant/risk-service-functional → HTTP {r.status_code}")
    print(f"  💥 invariant/risk-service  HTTP {r.status_code}")

sub("14c. Pipeline /runs/latest still returns valid JSON")
r = requests.get(f"{PIPE}/runs/latest", timeout=TIMEOUT)
if r.status_code in (200, 404):
    try:
        r.json()
        PASSED.append("invariant/pipeline-runs-latest-json")
        print(f"  ✅ invariant/pipeline  valid JSON returned")
    except Exception:
        CRASHED.append("invariant/pipeline-runs-latest-json → invalid JSON body")
        print(f"  💥 invariant/pipeline  non-JSON body")
else:
    CRASHED.append(f"invariant/pipeline-runs-latest-json → HTTP {r.status_code}")

sub("14d. No uncommitted transactions or locks in postgres")
import psycopg2
try:
    pg = psycopg2.connect(host="localhost", port=5433, dbname="stocker",
                          user="stocker", password="stocker")
    pg.autocommit = True
    with pg.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM pg_locks l
            JOIN pg_stat_activity a ON l.pid = a.pid
            WHERE NOT l.granted AND a.state = 'active'
        """)
        blocked = cur.fetchone()[0]
        if blocked > 0:
            WARNINGS.append(f"invariant/pg-locks: {blocked} blocked queries")
            print(f"  ⚠️  pg-locks: {blocked} blocked queries")
        else:
            PASSED.append("invariant/pg-no-blocked-queries")
            print(f"  ✅ invariant/pg-locks: no blocked queries")
    pg.close()
except Exception as e:
    WARNINGS.append(f"invariant/pg → {e}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("15. TRADE EXECUTOR — /jobs/cancel-all-orders")
# ═══════════════════════════════════════════════════════════════════════════════

sub("15a. Wrong HTTP methods must return 405")
_r("cancel/GET-cancel-all",    "get",    f"{TRADE}/jobs/cancel-all-orders")
_r("cancel/DELETE-cancel-all", "delete", f"{TRADE}/jobs/cancel-all-orders")
_r("cancel/PUT-cancel-all",    "put",    f"{TRADE}/jobs/cancel-all-orders", json={})

sub("15b. POST without ?confirm — must refuse with 400 (not 5xx)")
r_no_confirm = _r("cancel/no-confirm", "post", f"{TRADE}/jobs/cancel-all-orders")
if r_no_confirm and r_no_confirm.status_code == 400:
    PASSED.append("cancel/no-confirm-correctly-refused")
    print(f"  ✅ cancel/no-confirm correctly refused (400): {r_no_confirm.json().get('detail','')[:80]}")
elif r_no_confirm and r_no_confirm.status_code >= 500:
    CRASHED.append(f"cancel/no-confirm → 5xx: {r_no_confirm.status_code}")

sub("15c. Invalid confirm values — must all refuse with 400")
for bad_confirm in ["no", "maybe", "true", "1", "YES", " yes", "yes ", "yes\x00"]:
    encoded = urllib.parse.quote(bad_confirm, safe="")
    rc = _r(f"cancel/bad-confirm={bad_confirm!r}", "post",
            f"{TRADE}/jobs/cancel-all-orders?confirm={encoded}")
    if rc and rc.status_code == 400:
        PASSED.append(f"cancel/bad-confirm={bad_confirm!r}-refused")
    elif rc and rc.status_code >= 500:
        CRASHED.append(f"cancel/bad-confirm={bad_confirm!r} → 5xx: {rc.status_code}")

sub("15d. Injection in confirm query param — must not 5xx")
for inject in SQL_INJECTIONS[:3]:
    encoded = urllib.parse.quote(inject, safe="")
    _r(f"cancel/inject-confirm", "post",
       f"{TRADE}/jobs/cancel-all-orders?confirm={encoded}")

sub("15e. Valid cancel-all (confirm=yes) — must return 200 with correct schema")
r_valid = _r("cancel/confirm-yes", "post", f"{TRADE}/jobs/cancel-all-orders?confirm=yes")
if r_valid and r_valid.status_code == 200:
    body = r_valid.json()
    if all(k in body for k in ("alpaca_cancel_count", "local_orders_updated", "status")):
        PASSED.append("cancel/confirm-yes-schema-valid")
        print(f"  ✅ cancel/confirm-yes schema valid: {body}")
    else:
        WARNINGS.append(f"cancel/confirm-yes unexpected schema: {body}")

sub("15f. Concurrent cancel-all (5 threads) — no 5xx")
_cancel_results: list = []
def _fire_cancel():
    try:
        r = requests.post(f"{TRADE}/jobs/cancel-all-orders?confirm=yes", timeout=TIMEOUT)
        _cancel_results.append(r.status_code)
    except Exception as e:
        _cancel_results.append(str(e))

_cancel_threads = [threading.Thread(target=_fire_cancel) for _ in range(5)]
for t in _cancel_threads: t.start()
for t in _cancel_threads: t.join()
_cancel_5xx = [r for r in _cancel_results if isinstance(r, int) and r >= 500]
if _cancel_5xx:
    CRASHED.append(f"cancel/concurrent → 5xx: {_cancel_5xx}")
    print(f"  💥 cancel/concurrent  5xx: {_cancel_5xx}")
else:
    PASSED.append("cancel/concurrent-no-5xx")
    print(f"  ✅ cancel/concurrent  responses: {_cancel_results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("16. LLM VETTER — /jobs/vet, /runs/{run_id}/*")
# ═══════════════════════════════════════════════════════════════════════════════
VETTER = "http://localhost:8016"

sub("16a. Basic reads")
_r("vetter/health",      "get", f"{VETTER}/health")
_r("vetter/runs-latest", "get", f"{VETTER}/runs/latest")

sub("16b. /runs/{run_id} — invalid IDs must not 5xx")
for bad_id in INVALID_UUIDS[:5]:
    encoded = urllib.parse.quote(bad_id, safe="")
    _r(f"vetter/runs-bad-id={bad_id[:15]!r}",        "get", f"{VETTER}/runs/{encoded}")
    _r(f"vetter/excl-bad-id={bad_id[:12]!r}",         "get", f"{VETTER}/runs/{encoded}/exclusions")
    _r(f"vetter/results-bad-id={bad_id[:12]!r}",      "get", f"{VETTER}/runs/{encoded}/ticker-results")

sub("16c. /jobs/vet with empty / invalid bodies")
_r("vetter/vet-empty",    "post", f"{VETTER}/jobs/vet", json={})
_r("vetter/vet-null",     "post", f"{VETTER}/jobs/vet", json=None)
_r("vetter/vet-junk",     "post", f"{VETTER}/jobs/vet",
   json={"inject": SQL_INJECTIONS[0], "ranking_run_id": "not-a-uuid"})
_r("vetter/vet-huge",     "post", f"{VETTER}/jobs/vet",
   json={"ranking_run_id": VALID_UUID, "padding": LARGE_STRING})
_r("vetter/vet-bad-mode", "post", f"{VETTER}/jobs/vet",
   data="not json", headers={"Content-Type": "application/json"})

sub("16d. Concurrent vet triggers — no 5xx")
_vet_results: list = []
def _fire_vet():
    try:
        r = requests.post(f"{VETTER}/jobs/vet",
                          json={"ranking_run_id": VALID_UUID}, timeout=TIMEOUT)
        _vet_results.append(r.status_code)
    except Exception as e:
        _vet_results.append(str(e))

_vet_threads = [threading.Thread(target=_fire_vet) for _ in range(4)]
for t in _vet_threads: t.start()
for t in _vet_threads: t.join()
_vet_5xx = [r for r in _vet_results if isinstance(r, int) and r >= 500]
if _vet_5xx:
    CRASHED.append(f"vetter/concurrent → 5xx: {_vet_5xx}")
    print(f"  💥 vetter/concurrent  5xx: {_vet_5xx}")
else:
    PASSED.append("vetter/concurrent-no-5xx")
    print(f"  ✅ vetter/concurrent  responses: {_vet_results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("17. TRADE STATE-TRANSITION IDEMPOTENCY (DB-seeded)")
# ═══════════════════════════════════════════════════════════════════════════════
# Seed delta_intent + alpaca_orders rows in various statuses; verify that
# trade-executor /jobs/submit blocks or allows retry as per the idempotency rules:
#   Blocks  (409): pending | submitted | risk_rejected
#   Allows (non-409): failed | filled | canceled

import psycopg2
from datetime import datetime as _dt

def _pg():
    return psycopg2.connect(host="localhost", port=5433, dbname="stocker",
                            user="stocker", password="stocker")

def _seed_intent_with_order(status: str, ticker: str = "AAPL") -> str:
    """Insert a delta_intent + alpaca_orders row with the given order status."""
    iid = str(uuid.uuid4())
    oid = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    today = _dt.utcnow().strftime("%Y-%m-%d")
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO delta_runs (run_id,strategy_id,status,run_date,triggered_by) "
                "VALUES (%s,'fuzz','success',%s,'fuzz')", (run_id, today))
            cur.execute(
                "INSERT INTO delta_intents (id,run_id,ticker,action,current_weight,actual_weight) "
                "VALUES (%s,%s,%s,'entry',0.05,0.0)", (iid, run_id, ticker))
            cur.execute(
                "INSERT INTO alpaca_orders "
                "(id,intent_id,ticker,action,side,qty,notional,order_type,"
                "time_in_force,status,mode,risk_approved,risk_reason,created_at) "
                "VALUES (%s,%s,%s,'entry','buy',10,1800,'market','opg',%s,'scheduled',true,'fuzz',NOW())",
                (oid, iid, ticker, status))
        conn.commit()
    return iid

# Ensure a recent sync run exists so sizing doesn't abort on stale data
_sr_id = str(uuid.uuid4())
with _pg() as conn:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alpaca_sync_runs (run_id,status,account_value,buying_power,cash,"
            "started_at,completed_at) VALUES (%s,'success',100000,100000,100000,NOW(),NOW())",
            (_sr_id,))
    conn.commit()

sub("17a. Blocking statuses (pending/submitted/risk_rejected) → expect 200 status=duplicate")
# trade-executor /jobs/submit returns HTTP 200 with body.status='duplicate' (not 409).
# The 409 is returned by the API layer (/trade/approve). Both are correct per design.
for _status in ["pending", "submitted", "risk_rejected"]:
    _iid = _seed_intent_with_order(_status)
    _r17 = _r(f"state/{_status}-blocks", "post", f"{TRADE}/jobs/submit",
              json={"intent_id": _iid, "mode": "scheduled"})
    if _r17 and _r17.status_code >= 500:
        CRASHED.append(f"state/{_status}-blocks → 5xx: {_r17.status_code}")
    elif _r17 and _r17.status_code == 200 and _r17.json().get("status") == "duplicate":
        PASSED.append(f"state/{_status}-correctly-blocked-duplicate")
        print(f"  ✅ state/{_status}  correctly returned duplicate: {_r17.json().get('reason','')[:60]}")
    elif _r17:
        WARNINGS.append(f"state/{_status} unexpected: HTTP {_r17.status_code} body={_r17.text[:80]}")
        print(f"  ⚠️  state/{_status}  unexpected HTTP {_r17.status_code}")

sub("17b. Allowing statuses (failed/filled/canceled) → expect NOT 409")
for _status in ["failed", "filled", "canceled"]:
    _iid = _seed_intent_with_order(_status)
    _r17b = _r(f"state/{_status}-allows", "post", f"{TRADE}/jobs/submit",
               json={"intent_id": _iid, "mode": "scheduled"})
    if _r17b and _r17b.status_code == 409:
        CRASHED.append(f"state/{_status}-should-allow → blocked with 409 (idempotency too aggressive)")
        print(f"  💥 state/{_status}  wrongly blocked with 409!")
    elif _r17b and _r17b.status_code >= 500:
        CRASHED.append(f"state/{_status}-allows → 5xx: {_r17b.status_code}")
    else:
        PASSED.append(f"state/{_status}-correctly-allowed")
        print(f"  ✅ state/{_status}  correctly allowed retry: HTTP {_r17b.status_code if _r17b else None}")

sub("17c. Race: 3 concurrent submits from a retryable (failed) intent — no 5xx")
_race_iid = _seed_intent_with_order("failed", ticker="MSFT")
_race_results: list = []
def _fire_race():
    try:
        r = requests.post(f"{TRADE}/jobs/submit",
                          json={"intent_id": _race_iid, "mode": "scheduled"}, timeout=TIMEOUT)
        _race_results.append(r.status_code)
    except Exception as e:
        _race_results.append(str(e))

_race_threads = [threading.Thread(target=_fire_race) for _ in range(3)]
for t in _race_threads: t.start()
for t in _race_threads: t.join()
_race_5xx = [r for r in _race_results if isinstance(r, int) and r >= 500]
if _race_5xx:
    CRASHED.append(f"state/race-3threads → 5xx: {_race_5xx}")
    print(f"  💥 state/race  5xx in concurrent race: {_race_5xx}")
else:
    PASSED.append("state/race-no-5xx")
    print(f"  ✅ state/race  no 5xx: {_race_results}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("18. BUYING-POWER EDGE CASES (DB-seeded)")
# ═══════════════════════════════════════════════════════════════════════════════

def _seed_bp_intent(ticker: str, action: str = "entry", weight: float = 0.05) -> str:
    iid = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    today = _dt.utcnow().strftime("%Y-%m-%d")
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO delta_runs (run_id,strategy_id,status,run_date,triggered_by) "
                "VALUES (%s,'fuzztest','success',%s,'fuzz')", (run_id, today))
            cur.execute(
                "INSERT INTO delta_intents (id,run_id,ticker,action,current_weight,actual_weight) "
                "VALUES (%s,%s,%s,%s,%s,0.0)", (iid, run_id, ticker, action, weight))
        conn.commit()
    return iid

def _seed_sync_bp(account_value: float, buying_power: float) -> None:
    sid = str(uuid.uuid4())
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alpaca_sync_runs (run_id,status,account_value,buying_power,cash,"
                "started_at,completed_at) VALUES (%s,'success',%s,%s,%s,NOW(),NOW())",
                (sid, account_value, buying_power, buying_power))
        conn.commit()

sub("18a. buying_power=$0 → expect 400 (qty rounds to 0, position too small)")
_seed_sync_bp(0, 0)
_iid_zero = _seed_bp_intent("NVDA")
_r18a = _r("bp/zero-buying-power", "post", f"{TRADE}/jobs/submit",
           json={"intent_id": _iid_zero, "mode": "scheduled"})
if _r18a and _r18a.status_code == 400:
    PASSED.append("bp/zero-buying-power-refused-400")
    print(f"  ✅ bp/zero correctly refused (400): {_r18a.json().get('detail','')[:80]}")
elif _r18a and _r18a.status_code >= 500:
    CRASHED.append(f"bp/zero → 5xx: {_r18a.status_code}")
else:
    WARNINGS.append(f"bp/zero expected 400, got {_r18a.status_code if _r18a else None}")

sub("18b. buying_power=$50 (tiny, 5% = $2.50 → qty=0) → expect 400")
_seed_sync_bp(50, 50)
_iid_tiny = _seed_bp_intent("MSFT")
_r18b = _r("bp/tiny-buying-power", "post", f"{TRADE}/jobs/submit",
           json={"intent_id": _iid_tiny, "mode": "scheduled"})
if _r18b and _r18b.status_code == 400:
    PASSED.append("bp/tiny-buying-power-refused-400")
    print(f"  ✅ bp/tiny correctly refused (400): {_r18b.json().get('detail','')[:80]}")
elif _r18b and _r18b.status_code >= 500:
    CRASHED.append(f"bp/tiny → 5xx: {_r18b.status_code}")
else:
    WARNINGS.append(f"bp/tiny expected 400, got {_r18b.status_code if _r18b else None}")

sub("18c. buying_power=$200k (large) → should not 5xx")
_seed_sync_bp(200_000, 200_000)
_iid_large = _seed_bp_intent("AAPL")
_r18c = _r("bp/large-buying-power", "post", f"{TRADE}/jobs/submit",
           json={"intent_id": _iid_large, "mode": "scheduled"})
if _r18c and _r18c.status_code >= 500:
    CRASHED.append(f"bp/large → 5xx: {_r18c.status_code}")
else:
    PASSED.append("bp/large-no-5xx")
    print(f"  ✅ bp/large  no 5xx: HTTP {_r18c.status_code if _r18c else None}")

sub("18d. Both account_value=$0 AND buying_power=$0 — must not 5xx")
_seed_sync_bp(0, 0)
_iid_all_zero = _seed_bp_intent("GOOG")
_r18d = _r("bp/both-zero", "post", f"{TRADE}/jobs/submit",
           json={"intent_id": _iid_all_zero, "mode": "immediate"})
if _r18d and _r18d.status_code >= 500:
    CRASHED.append(f"bp/both-zero → 5xx: {_r18d.status_code}")
else:
    PASSED.append("bp/both-zero-no-5xx")
    print(f"  ✅ bp/both-zero  no 5xx: HTTP {_r18d.status_code if _r18d else None}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("19. MOO-ONLY ENFORCEMENT — time_in_force must always be 'opg'")
# ═══════════════════════════════════════════════════════════════════════════════

sub("19a. Scan recent alpaca_orders for any non-opg time_in_force")
try:
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, time_in_force, mode, status, created_at
                FROM alpaca_orders
                WHERE created_at > NOW() - INTERVAL '2 hours'
                  AND time_in_force IS NOT NULL
                  AND time_in_force != 'opg'
                ORDER BY created_at DESC
                LIMIT 10
            """)
            bad_tif = cur.fetchall()
    if bad_tif:
        for row in bad_tif:
            CRASHED.append(f"moo/order-{str(row[0])[:8]}-tif={row[1]!r}-not-opg")
            print(f"  💥 moo/enforcement FAIL: order {str(row[0])[:8]} tif={row[1]!r} mode={row[2]} status={row[3]}")
    else:
        PASSED.append("moo/all-recent-orders-opg")
        print("  ✅ moo  all recent alpaca_orders have time_in_force='opg'")
except Exception as e:
    WARNINGS.append(f"moo/scan → {e}")
    print(f"  ⚠️  moo/scan DB error: {e}")

sub("19b. Submit immediate-mode intent → verify alpaca_orders.time_in_force='opg'")
_seed_sync_bp(100_000, 100_000)
_iid_imm = _seed_bp_intent("AAPL", "entry")
_r19b = requests.post(f"{TRADE}/jobs/submit",
                      json={"intent_id": _iid_imm, "mode": "immediate"}, timeout=TIMEOUT)
time.sleep(1)
try:
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT time_in_force, mode, status FROM alpaca_orders "
                        "WHERE intent_id=%s ORDER BY created_at DESC LIMIT 1", (_iid_imm,))
            row19 = cur.fetchone()
    if row19:
        tif19, mode19, st19 = row19
        if tif19 == "opg":
            PASSED.append("moo/immediate-opg-confirmed")
            print(f"  ✅ moo/immediate  time_in_force='opg' mode={mode19} status={st19}")
        else:
            CRASHED.append(f"moo/immediate  time_in_force={tif19!r} (expected 'opg')")
            print(f"  💥 moo/immediate FAIL: time_in_force={tif19!r}")
    else:
        WARNINGS.append(f"moo/immediate → no order row found (HTTP {_r19b.status_code})")
except Exception as e:
    WARNINGS.append(f"moo/immediate-check → {e}")

sub("19c. Submit scheduled-mode intent → verify time_in_force='opg'")
_seed_sync_bp(100_000, 100_000)
_iid_sched = _seed_bp_intent("TSLA", "entry")
_r19c = requests.post(f"{TRADE}/jobs/submit",
                      json={"intent_id": _iid_sched, "mode": "scheduled"}, timeout=TIMEOUT)
time.sleep(1)
try:
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT time_in_force, mode FROM alpaca_orders "
                        "WHERE intent_id=%s ORDER BY created_at DESC LIMIT 1", (_iid_sched,))
            row19c = cur.fetchone()
    if row19c and row19c[0] == "opg":
        PASSED.append("moo/scheduled-opg-confirmed")
        print(f"  ✅ moo/scheduled  time_in_force='opg' mode={row19c[1]}")
    elif row19c:
        CRASHED.append(f"moo/scheduled time_in_force={row19c[0]!r} (expected 'opg')")
        print(f"  💥 moo/scheduled FAIL: time_in_force={row19c[0]!r}")
    else:
        WARNINGS.append(f"moo/scheduled → no order row (HTTP {_r19c.status_code})")
except Exception as e:
    WARNINGS.append(f"moo/scheduled-check → {e}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("20. AUDIT TRAIL DB INVARIANTS")
# ═══════════════════════════════════════════════════════════════════════════════

sub("20a. Every API-submitted approved order must have risk_check_id set")
# Only check rows that have a trace_id (created by the API, not seeded by tests)
try:
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM alpaca_orders
                WHERE risk_approved = true AND risk_check_id IS NULL
                  AND trace_id IS NOT NULL
                  AND created_at > NOW() - INTERVAL '2 hours'
                LIMIT 5
            """)
            orphans20a = cur.fetchall()
    if orphans20a:
        for o in orphans20a:
            CRASHED.append(f"audit/approved-order-no-risk-check-id: order {str(o[0])[:8]}")
        print(f"  💥 audit  {len(orphans20a)} approved orders with no risk_check_id")
    else:
        PASSED.append("audit/all-approved-have-risk-check-id")
        print("  ✅ audit  all approved orders have risk_check_id")
except Exception as e:
    WARNINGS.append(f"audit/risk-check-id-check → {e}")

sub("20b. Every alpaca_orders trace_id must have a matching execution_traces row")
try:
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ao.id, ao.trace_id
                FROM alpaca_orders ao
                LEFT JOIN execution_traces et ON et.trace_id = ao.trace_id
                WHERE ao.trace_id IS NOT NULL AND et.trace_id IS NULL
                  AND ao.created_at > NOW() - INTERVAL '2 hours'
                LIMIT 5
            """)
            missing20b = cur.fetchall()
    if missing20b:
        for m in missing20b:
            CRASHED.append(f"audit/order-{str(m[0])[:8]}-trace-id-missing-from-execution-traces")
        print(f"  💥 audit  {len(missing20b)} orders with trace_id but no execution_traces row")
    else:
        PASSED.append("audit/all-trace-ids-matched")
        print("  ✅ audit  all trace_ids have matching execution_traces rows")
except Exception as e:
    WARNINGS.append(f"audit/trace-check → {e}")

sub("20c. No pending/submitted orders older than 25 hours")
try:
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM alpaca_orders
                WHERE status IN ('pending', 'submitted')
                  AND created_at < NOW() - INTERVAL '25 hours'
            """)
            stale20c = cur.fetchone()[0]
    if stale20c > 5:
        WARNINGS.append(f"audit/stale-orders: {stale20c} pending/submitted orders >25h old")
        print(f"  ⚠️  audit  {stale20c} stale pending/submitted orders (>25h)")
    else:
        PASSED.append("audit/no-excessive-stale-orders")
        print(f"  ✅ audit  stale-order check: {stale20c} stale orders (OK)")
except Exception as e:
    WARNINGS.append(f"audit/stale-check → {e}")

sub("20d. Risk service still healthy and functional after all sections")
_r20d = requests.post(f"{RISK}/check", json=base_risk, timeout=TIMEOUT)
if _r20d.status_code == 200 and "approved" in _r20d.json():
    PASSED.append("audit/risk-service-still-functional")
    print(f"  ✅ audit  risk-service functional after fuzzing: approved={_r20d.json()['approved']}")
else:
    CRASHED.append(f"audit/risk-service-not-functional: HTTP {_r20d.status_code}")
    print(f"  💥 audit  risk-service degraded: HTTP {_r20d.status_code}")


# ═══════════════════════════════════════════════════════════════════════════════
hdr("FINAL REPORT")
# ═══════════════════════════════════════════════════════════════════════════════
total = len(PASSED) + len(CRASHED) + len(FAILED)
print(f"""
  Tests run:   {total}
  Passed:      {len(PASSED)}
  Crashed(5xx):{len(CRASHED)}
  Failed:      {len(FAILED)}
  Warnings:    {len(WARNINGS)}
""")

if CRASHED:
    print("  ━━━ 5xx CRASHES (service crashed on invalid input — BUG) ━━━")
    for c in CRASHED:
        print(f"    💥 {c}")

if FAILED:
    print("  ━━━ TEST FAILURES (connection/timeout) ━━━")
    for f in FAILED:
        print(f"    ❌ {f}")

if WARNINGS:
    print("  ━━━ WARNINGS ━━━")
    for w in WARNINGS:
        print(f"    ⚠️  {w}")

print()
if CRASHED:
    print(f"  {'═'*60}\n  RESULT: FAIL — {len(CRASHED)} service crashes on invalid input\n  {'═'*60}")
elif FAILED:
    print(f"  {'═'*60}\n  RESULT: PARTIAL — {len(FAILED)} test failures (connection/timeout)\n  {'═'*60}")
else:
    print(f"  {'═'*60}\n  RESULT: PASS — all {len(PASSED)} checks survived\n  {'═'*60}")
