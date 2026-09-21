# Conversion basis fix: bounded economic certificate

This is the retained certificate for commit `fc8afa7e`, before the subsequently
authorized cash-adjusted strategy policy. See the
[cash-adjusted certificate](../cash_conversion/README.md) for the current rule.
The JSON evidence here is preserved unchanged. To reproduce this historical
phase, use its recorded commit's certificate script and source.

**PASS for the missing-predecessor conversion fix:** BRL/TEVA on 2008-12-23
and its following session complete through the canonical production kernel.
Cash, delivered shares, independently recomputed closing NAV, immutable prior
state and JSON restart parity agree. This is not a certification of the complete
historical strategy return or a production checkpoint migration.

Verified base: `6f054282e48e46252ec18374b2a56f25b60ebca3`. Its Wealth Core and
`sentinel/core` files match the previously simulated production revision
`624395dd04c48af7de3a8930cfd586ca2cc81245` before this change.

## Defect and repair

`wealth_core/adapter.py:step_session` supplied `None` for the predecessor basis
when BRL had no event-session bar. `terminal.py:apply_terminal` correctly refused
`MISSING_CONVERSION_SIGNAL_BASIS`, even though the canonical feed retained
BRL's immediately prior raw/owned-signal observation. The adapter therefore
could not process a completed acquisition after the predecessor stopped quoting.

`feed.py:Feed.prior_conversion_basis` now validates the retained permanent ID,
prior market session/index, aligned positive finite observations and publication
anchor. `run.py:run_sessions` passes this evidence through the shared live/replay
path. The adapter uses it only when the predecessor bar is absent. Existing
current-bar precedence, delivered-basis and current valuation requirements stay
in force. Terminal result evidence includes the source basis and participates in
the final result hash. There is no new persisted schema or separate strategy book.

## Independent economic oracle

The acquisition terms were $39.90 cash plus 0.6272 TEVA ADS per BRL share.
Sources: [transaction terms](https://www.sec.gov/Archives/edgar/data/818686/000081868608000117/barr180708.htm)
and [December 23 completion](https://ir.tevapharm.com/news-and-events/press-releases/press-release-details/2008/Teva-Completes-Acquisition-of-Barr/default.aspx).

For the checkpoint's 70 BRL shares, decimal arithmetic gives:

| Component | Expected | Observed |
|---|---:|---:|
| Gross TEVA entitlement | 43.904 ADS | 43.904 ADS |
| Whole TEVA shares retained | 43 | 43 |
| Fraction settled in cash | 0.904 | 0.904 |
| Contract cash | $2,793.00 | $2,793.00 |
| Fraction cash at retained $41.82 assumption | $37.80528 | $37.80528 |
| Total cash increase | $2,830.80528 | $2,830.8052800000005 |

$41.82 is the retained research cash-in-lieu assumption, not a paying-agent
settlement assertion. At TEVA's $41.99 closing price, the delivered shares plus
both cash components are worth $4,636.37528, versus BRL's previous $4,606 mark.
The synthetic regression also checks raw opening NAV and different source and
delivered signal scales (2 and 0.5); assuming both scales are one fails that oracle.

| Session | Core close NAV | Independent recomputation | Restart |
|---|---:|---:|---|
| 2008-12-23 | $91,309.6960287378 | $91,309.69602873779 | Identical state hash |
| 2008-12-24 | $91,289.0550787378 | $91,289.055078737788 | Identical state hash |

Disabling only the fallback in memory reproduces the original unresolved BRL
position. Enabling it clears that blocker. Sentinel holds **0% Core exposure**
on both sessions, so this conversion does not contribute to the controlled
account's return over these two days.

## Existing strategy policy exposed by the case

The delivered TEVA episode queues a trailing stop: its translated peak is
$106.8080357143 versus a $41.99 close. The conversion formula divides the old
peak by the exchange ratio without subtracting contractual cash. This is the
existing documented signal convention, implemented in
`terminal.py:_apply_conversion`; the retained reference's `core/champion.py`
also divides `s.peak` by `_ratio`. It is not introduced by this fix.

The economic receipt itself gained $30.37528 relative to the prior mark, so
this stop must not be described as a 60% loss of total deal proceeds. Whether
the strategy should instead adjust its stop anchor for cash consideration is a
separate strategy-policy question. This certificate validates settlement and
valuation, and reports this existing behavior rather than silently changing it
or claiming the stop policy is economically optimal.

## Matched-date performance

July 31, 2006 through December 24, 2008, using the retained naturally formed
book and reconstructed classification scenario. The current baseline is
$92,527.41663482299; it is not the original unknown-classification replay's
$90,886.70559 baseline. Current results use the retained prefix through December
22 plus this explicitly identified two-session source fork.

| Path | Multiple | CAGR |
|---|---:|---:|
| Current strategy, classification-aligned scenario | 1.347425x | 13.222955% |
| Retained reference, same dates | 1.316499x | 12.133351% |
| SPY, total-return factors, same dates | 0.713798x | -13.100191% |

These are partial-period results, not a confirmation of the full 56.265349x run.
See [matched-performance.json](matched-performance.json).

## Verification

Python 3.12; local shared/root/runtime paths in `PYTHONPATH`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `-B`, cache provider disabled and a fresh
workspace `--basetemp` per invocation:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=<fresh-workspace-dir> tests/wealth_core/test_conversion_prior_basis.py -k absent_predecessor
```

Before implementation: **1 failed**, specifically BRL remained BRL instead of
becoming TEVA. After implementation the initial new file passed all 13 cases.

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=<fresh-workspace-dir> tests/wealth_core/test_conversion_prior_basis.py tests/wealth_core/test_adapter.py tests/wealth_core/test_terminal.py tests/wealth_core/test_exact_corporate_action_economics.py tests/wealth_core/test_feed_stream_validation.py tests/wealth_core/test_restart_matrix.py tests/wealth_core/test_golden_fixture.py tests/sentinel/test_terminal_leadership_return.py tests/sentinel/test_terminal_split_return.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_operational_parity.py
```

**204 passed, 2 existing strict xfails, 28 setup errors.** The setup errors are
all PostgreSQL tests in `test_rolling_daily.py`: the Linux-only fixture calls
`os.geteuid`, unavailable on this Windows host. No assertion in those tests ran;
Linux CI remains necessary. The two existing golden pin xfails were not changed.

After adding four current-bar/delivered-basis/publication cases:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=<fresh-workspace-dir> tests/wealth_core/test_conversion_prior_basis.py tests/v5/test_publication_regressions.py -k "prior_basis or publication or signal_anchor or changing_publications"
```

**46 passed** (includes rerunning the new conversion file). Four collection
warnings concern imported asyncio marks with plugin autoload disabled.

The stale-basis guard was removed **in memory only** and its parametrized test
failed at the economic assertion: stale BRL improperly became TEVA. Source was
unchanged. A fallback-disabled golden control matches all seven parity hashes
and the result hash; [golden-control.json](golden-control.json) proves this fix
adds no golden-scenario drift. No fixture was repinned.

`python -B -m pyflakes` passed for the three changed production modules, new
conversion test and certificate script. `git diff --check` passed.

## Reproduce the real checkpoint certificate

Use [certify.py](../../research/conversion_basis/certify.py) with read-only
checkouts for the PR #428 input readers and PR #426 harness. All production
imports are asserted to resolve to this fix's checkout. Example:

```text
python -B research/conversion_basis/certify.py --readers <PR428-checkout> --harness <PR426-checkout> --checkpoint <segment-002/latest-checkpoint.json> --archive <pit-source-5bdc6b39.zip> --sfp <SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz> --supplements <economic-replay-60m-20260921/supplements.json> --output <new-certificate.json>
```

[certificate.json](certificate.json) retains original/new strategy identities,
source file hashes, checkpoint hash, input hashes, failure control and both
sessions' witnesses. Only `wealth_core_source_sha256` changes in the strategy
identity. The original checkpoint is not admitted as a production continuation:
a deep-copied in-memory state receives the explicitly reported new identity.
Checkpoint and supplement hashes are verified unchanged at the end. Original
replay worktrees, inputs, supplements, checkpoints, containers and outputs remain
untouched; no NAS or broker access occurred.
