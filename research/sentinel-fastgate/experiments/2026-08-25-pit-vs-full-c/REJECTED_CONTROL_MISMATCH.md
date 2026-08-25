# Rejected Orion PIT / Full-C replay attempt

**Status: REJECTED. Do not use these economics as evidence.**

This record preserves the first completed local implementation attempt for the two preregistered Orion experiments. The run completed through 2026-07-31, but it failed the mandatory legacy-control parity gate.

## Required control

Frozen retained Orion 20-year research result:

- CAGR: 23.1327%
- Sharpe: 1.2357
- max drawdown: -21.6958%
- ending multiple: 64.1958x

The attempted harness produced legacy Orion CAGR 16.0474628801%, so the implementation is not economically identical to the authoritative Orion replay. All candidate outputs are therefore rejected.

## Local harness identity

- local filename: `orion_ab_runner.py`
- size: 34,091 bytes
- SHA-256: `b366ef7905407a0d91c270a693ddc86b52ff0003af1ed3104c50b8df02a8953c`
- replay sessions: 5,032
- decision end: 2026-07-31

The exact local source must not be promoted as the experiment harness until its differences from the authoritative current-main/#244 replay semantics are repaired and the control fingerprint passes.

## Rejected output hashes

- `summary.json`: `002f408d3be03532ac9a87c52f075a24136b69a795f4346e8647789f4955a16b`
- `legacy_daily.csv`: `8550ab3faa12f12492e122b00ff8c77ccba4d319a8b4f464c93e758640ad2e8d`
- `pit_ff12_daily.csv`: `a0dcdf189578a26b9873aef45855cbe999e76e7e966fd0cb04df98df87dd864d`
- `full_c_daily.csv`: `5e3c0bcdf0d77798b6f8140a8df2dc4db88e76f9130a20c07e6082d8b750978e`

## Known implementation discrepancies to repair

Compared with the retained current-main/#244-style replay harness, this rejected attempt simplified several economically important boundaries, including eligibility/metadata handling, ACTIONS/terminal-event processing, and Wealth Core/accounting state. It also joined SIC using the current TICKERS `secfilings` CIK rather than the retained causal Form 3/4/5 issuer timeline.

No Experiment 1 or Experiment 2 result is accepted until:

1. the legacy arm reproduces the frozen Orion control fingerprint/session path;
2. Experiment 1 changes only current Sharadar sector -> causal SEC SIC->FF12;
3. Experiment 2 changes only PIT breadth peer construction -> preregistered Full-C Breadth v1;
4. all histories are strict prior-only and all outputs/provenance are retained on this research branch.

This file is research-only and must not be merged as a production strategy activation.