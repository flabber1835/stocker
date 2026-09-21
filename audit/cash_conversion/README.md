# Cash-adjusted conversion: economic certificate

**PASS for the bounded cash-adjusted continuation rule.** The rule preserves
percentage drawdown through a value-preserving distribution, recognizes a real
loss in the acquisition package, and does not let distributed cash shield later
losses in the remaining stock. It is an intentional strategy change, authorized
after the preceding [missing-basis investigation](../conversion_basis/README.md).

Base verification: current `origin/main` was
`6f054282e48e46252ec18374b2a56f25b60ebca3`; work extends PR #429 from
`fc8afa7e3dac11fdce6fca290a54062b4850f1b4` in its isolated feature worktree.

## Economic rule and oracle

The holder receives `C` cash (including fractional-share cash) and `Q` whole
delivered shares worth `P` each at the conversion-session open. Allocate
historical entry/peak position value to the retained equity in proportion to
`Q*P / (C+Q*P)`. Dividing that retained historical value among `Q` shares gives
the new per-share reference. Source and delivered signal bases are explicitly
translated; age, review state, source provenance and existing pending exits
remain intact. The documented formula is in
[wealth-core-v1.md](../../docs/wealth-core-v1.md#cash-adjusted-continuation-2026-09-21).

Independent example: an old $120 peak and $100 entry, paid as $60 cash plus
$40 stock, give the continuing stock a $48 peak and $40 entry reference.
Its 16.6667% drawdown is unchanged. An opening package of only $70 retains its
41.6667% loss from the old $120 peak and triggers the stop. If the stock falls
from $40 to $20 after a value-preserving conversion, it can trigger the stop;
cash already distributed to the portfolio is not credited to it again.

The rule uses the event-session **open**, never the later close, to establish
the allocation. Missing/invalid opening value blocks cash and share settlement
before any episode is changed. Entirely cash-settled positions need no continuing
signal reference. Integral stock-only conversions retain their previous numeric
path. Fractional entitlements floor once per holder; their cash (including zero
cash paid for a lost fraction) is included in the economic outcome.

## Actual Barr/Teva reproduction

Input: the unchanged December 22, 2008 checkpoint, SHA256
`fecaa24467a2d0c1e124a8033bd6d8ea3f366b5eec223970f479b5ae940fcdbc`.
The input archive, classification overlay and corporate-action supplements are
the same as the prior certificate. The $41.82 cash-in-lieu price remains a
research assumption; no new settlement evidence was introduced.

Independent decimal calculation:

```text
70 BRL * 0.6272 = 43.904 TEVA ADS
whole shares = 43; fraction = 0.904
cash = 70 * $39.90 + 0.904 * $41.82 = $2,830.80528
opening package = cash + 43 * $42.11 = $4,641.53528
old peak value = 70 * $66.99 = $4,689.30
new TEVA peak = $4,689.30 * $42.11 / $4,641.53528 = $42.5433420383
```

Both actual signal scales are one. The synthetic tests also use unequal scales
of 2 and 0.5 to falsify an implementation that accidentally assumes equality.

| Observation | Ratio-only control | Cash-adjusted rule |
|---|---:|---:|
| TEVA peak on December 23 | $106.8080357143 | $42.5433420383 |
| Stop queued at $41.99 close | Yes | No |
| December 23 Core NAV | $91,309.6960287378 | $91,309.6960287378 |
| December 24 TEVA sale | 43 shares at $41.65 | No sale |
| December 24 sale cost | $1.79095 | $0 |
| December 24 Core NAV | $91,289.0550787378 | $91,299.8760287378 |

The $10.82095 next-day difference equals 43 shares times the $0.21
open-to-close move, plus the avoided $1.79095 sale cost. This price outcome was
not used to choose the policy. Cash, shares and conversion-day NAV are identical
between policies. Sentinel held 0% Core exposure, so controlled account NAV is
identical on both days. The previous matched-date current/reference/SPY table
therefore remains unchanged; no full-history performance claim follows.

Both sessions match exactly after JSON state restoration. Each prior envelope
remains unchanged. Closing NAV is separately recomputed as cash plus receivables
plus quantities times current raw marks. [certificate.json](certificate.json)
contains source/input identities, package arithmetic, stop decisions, state
hashes, the old-rule sale ledger, and both canonical production witnesses.
The control changes only the reference-scaling function in memory and is labelled
as a policy ablation, not as a separately admitted production source identity.

## Targeted tests and falsifiers

Tests ran on Python 3.12 with local shared/root/runtime paths in `PYTHONPATH`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `-B`, cache disabled and a new workspace
`--basetemp` each time.

Before implementation, the new value-preservation test failed at its independent
peak oracle: expected 24 signal units, observed 60. The new suite now contains
15 cases covering unchanged drawdown, real loss, premium, subsequent stock loss,
fractional cash, multiple lots, missing/invalid opening evidence, no close-based
rescue, fully cash-settled entitlements, old pending exits, restart, numeric
representability and a zero-value fractional settlement.

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=<fresh-workspace-dir> tests/wealth_core/test_conversion_cash_rebase.py tests/wealth_core/test_conversion_prior_basis.py tests/wealth_core/test_terminal.py tests/wealth_core/test_exact_corporate_action_economics.py tests/wealth_core/test_conversion_entitlements.py tests/wealth_core/test_conversion_collision.py tests/wealth_core/test_terminal_opening_causality.py tests/wealth_core/test_adapter.py tests/wealth_core/test_issuer_rebinding.py tests/wealth_core/test_terminal_audit.py tests/wealth_core/test_restart_matrix.py tests/wealth_core/test_golden_fixture.py
```

**257 passed, 2 existing strict xfails.** This invocation preceded addition of
the final two numeric/fractional boundary cases, which passed in the next run:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=<fresh-workspace-dir> tests/wealth_core/test_conversion_cash_rebase.py tests/sentinel/test_operational_parity.py tests/sentinel/test_terminal_leadership_return.py tests/sentinel/test_terminal_split_return.py tests/v5/test_publication_regressions.py
```

**74 passed.** Four collection warnings concern imported asyncio marks with
plugin autoload disabled. No database/NAS/broker access is needed by these checks.

The new numeric preflight was removed in memory and its falsifier failed on an
actual forbidden cash mutation ($10,000 became $10,020), proving that all lots
must be checked before settlement. An in-memory closing-price fallback also
failed the missing-opening witness by improperly applying the conversion.
The old ratio-only implementation fails the
drawdown oracle; the case also verifies cash cannot protect subsequent losses.

Existing entitlement tests now supply a delivered opening valuation. The
pending-exit restart fixture uses a priced but nontradeable delivered bar, so it
still proves orders survive until executable. Missing-opening tests explicitly
assert the stronger pre-settlement refusal. No expected cash/share entitlements
or original golden files were changed.

The golden scenario has an intentional policy difference starting at **S190**,
the first affected conversion. Its ratio-only control reproduces the previous
`11566dc3...` result hash exactly; normalized input remains identical. New policy
hash `aaf4e592...` and the event attribution are retained in
[golden-policy-delta.json](golden-policy-delta.json). The two pre-existing pinned
result tests remain strict xfails. No golden was repinned or guard relaxed.

Changed-file `python -B -m pyflakes` and `git diff --check` passed. Full deployment
certification and the full twenty-year performance run remain outside this scope.

## Reproduction and preservation

```text
python -B research/conversion_basis/certify.py --readers <PR428-checkout> --harness <PR426-checkout> --checkpoint <segment-002/latest-checkpoint.json> --archive <pit-source-5bdc6b39.zip> --sfp <SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz> --supplements <economic-replay-60m-20260921/supplements.json> --output <new-certificate.json>
```

The script checks input hashes, admits an explicitly labelled in-memory source
fork, asserts production imports resolve to this checkout, and rechecks the
original checkpoint and supplements afterward. Its output must be a new file.
The prior PR phase's evidence remains untouched in `audit/conversion_basis/`.
Neither the old simulation's source, inputs, supplements, checkpoints, outputs
nor its containers were changed. There was no NAS or broker access.
