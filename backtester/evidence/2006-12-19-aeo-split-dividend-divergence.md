# 2006-12-19 AEO split + dividend equivalence divergence

## Scope

This note records the next genuine research/production equivalence divergence found after the retained-research REY terminal-grace repair. It is backtester certification evidence only; `main` is not modified by this repair.

## Authoritative replay

- Workflow run: `33341153930`
- Backtester branch: `research/backtester-terminal-grace-fix`
- Backtester SHA: `5b61e64faad7c17a85a58e4101a4b63dbd16a918`
- Pinned production source: `887f479b15ad861313da666ad698034d3847121c`
- Canonical PIT dataset hash: `08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6`
- Uploaded artifact: `9741180868`
- Artifact ZIP SHA256: `01517206350483a6b8a8c81f7ba2e5fc361192d6e46170dc341c2bc40bdde8fe`

The replay completed both engines and passed canonical input byte parity. The first remaining NAV divergence was:

- session: `2006-12-19`
- research NAV: `1.148808928837702`
- production NAV: `1.1488578584958746`
- absolute NAV delta: `4.8929658172713886e-05`

Wealth Core equity was effectively identical through 2006-12-18 (difference about two mills from independent cent rounding), then diverged on 2006-12-19:

- research Wealth Core equity: `104183299.5830102`
- production Wealth Core equity: `104187736.92`
- production minus research: `4437.336989805102`

## Canonical event evidence

Canonical PIT observation for AEO on 2006-12-19:

- security id: `226714775113304174`
- raw open: `31.50`
- raw close: `31.47`
- signal close: `31.47`
- split ratio: `1.5`
- dividend per share: `0.075`

Canonical actions on the same effective session contain both:

- `split`, canonical value `1.5`, disposition `corroborated_direct`
- `dividend`, canonical value `0.075`, disposition `RAW_SHARE_DOMAIN_CONVERTED`

This means the dividend amount is already expressed in the current raw-share domain for the effective session.

## Root cause

The retained research replay captured `prior_qty` before applying the session split transformation. It later used that stale pre-split quantity to calculate the dividend entitlement.

For the AEO holding in this replay:

- prior-close shares before split: `118329`
- post-split shares: `118329 * 1.5 = 177493.5`
- dividend: `$0.075/share`
- research under-credit: `(177493.5 - 118329) * 0.075 = $4437.3375`

That matches the observed Wealth Core equity divergence (`$4437.336989805102`) to independent cent-rounding noise.

Production ordering is economically correct for this canonical representation: transform the carried prior-close position into the effective session raw-share domain first, then measure the dividend entitlement on that transformed quantity. The entitlement must still be captured before same-open exits or purchases so it remains a prior-close entitlement.

## Backtester-only repair

`backtester/research_terminal_grace_overlay.py` now moves the prior-close entitlement capture:

1. after split-domain transformations;
2. before terminal/open exit processing;
3. before same-open entry fills.

An exact regression test is added at:

`tests/backtester/test_research_split_dividend_ordering.py`

The regression locks both the transformed-source ordering and the exact AEO economic boundary (`$4437.3375`).

## Retry-4 harness finding

Workflow run `33344830842` did **not** reach the economic replay. All regression tests, including the exact AEO test, passed, but the runtime overlay failed while generating the canonical-PIT research source:

`RuntimeError: remove pre-split dividend entitlement capture: expected one source seam, found 0`

The reason was transform ordering, not strategy logic. Without `CANONICAL_PIT_DATASET` set, the retained source still contains the ordinary price-factor split loop. During the actual certification run, the canonical transform replaces that split loop with a direct `canonicalsplit` loop before the AEO overlay is applied. The first overlay version incorrectly matched the ordinary split-loop interior.

The corrected overlay now treats `prior_qty` as its own unique economic seam: it removes that standalone capture and reinserts it at the stable `dayact` boundary, which follows both the ordinary and canonical split implementations and precedes all same-open exit/buy processing. A dedicated regression now covers the canonical `canonicalsplit` variant as well as the ordinary generated form.

Retry-4 artifact:

- workflow run: `33344830842`
- backtester SHA: `50690f63051e735532bec5d6dfe415e28a92cc87`
- artifact ID: `9741662646`
- artifact ZIP SHA256: `8a1a884b041e9eec90fa7c9825a910c38e916b165f9b4e17f3e5cf7befe359f7`

This retry is classified as a harness/source-transform failure; it produced no new research/production economic divergence evidence.

## Certification consequence

This finding is a retained research backtester event-ordering defect, not a canonical PIT data defect. The bounded 2006-2007 research/production equivalence replay must be rerun after the repair. If another divergence remains, the next first divergence becomes the new investigation boundary.
