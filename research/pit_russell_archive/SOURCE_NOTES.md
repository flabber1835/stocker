# Russell 3000 PIT source notes

Status: **RESEARCH ONLY — source inventory, not certified corpus authority**

These notes record contemporaneous/public evidence found while testing the Russell 3000 eligibility-overlay hypothesis. They are intentionally separated from production and backtester authority.

## Core hypothesis supported by source evidence

Candidate rule:

> A security is eligible for Wealth Core only if it appears in the causally available Russell 3000 membership universe for that annual period. Russell membership supplies the security-type/investability eligibility decision. Sharadar supplies observed market data used by the strategy.

This would remove the strategy's need to reconstruct historical Sharadar `category`/share-class eligibility across the broad market. Stable security identity, market observations, corporate-action handling, and terminal-position economics remain separate requirements.

## 2006 — contemporaneous Russell additions artifact

Source:

- https://media.corporate-ir.net/media_files/irol/65/65508/Russell3000.pdf

Observed evidence:

- Document title identifies Russell 3000 additions.
- It states that the Russell U.S. indexes include only common stocks belonging to corporations incorporated in the United States and its territories.
- It identifies Russell 3000 additions as of June 16, 2006.
- It states that a deletions list was also available.
- It states final membership lists for Russell 1000, 2000, 3000 and Microcap would be posted July 3, 2006.
- It documents a 2006 methodology change: preliminary-list deletions caused by corporate actions/delisting would not be replaced; other preliminary changes were limited to discovered errors.

Research significance:

1. This is direct contemporaneous support for using Russell membership as a common-stock eligibility authority for this historical period.
2. It gives a causal publication schedule for 2006.
3. It establishes an authoritative delta-reconstruction path if the final full list cannot be recovered: accepted prior universe + dated additions/deletions, subject to holdout validation.

## 2007 — NASDAQ reconstitution schedule

Source:

- https://listingcenter.nasdaq.com/assets/rulebook/nasdaq/rules/Issuer_Alert_2007-004.pdf

Observed evidence:

- NASDAQ Issuer Alert dated June 20, 2007.
- Preliminary Russell 3000 additions/deletions published June 11.
- Updates published June 15 and June 22.
- Reconstitution became final after the close June 22.
- Final membership lists were scheduled to be posted June 25.

Research significance:

This provides independent contemporaneous evidence for when 2007 membership information became knowable and when the reconstituted index became effective. A Wayback capture timestamp can therefore be checked against an independently established publication/effective-time contract.

## 2008 — contemporaneous company announcement

Source:

- https://ir.agnc.com/news-releases/news-release-details/agnc-added-preliminary-list-russell-3000

Observed evidence:

- AGNC announcement dated June 25, 2008.
- It states AGNC was on Russell's preliminary list for addition at the close June 27, 2008.
- It states final index membership would be posted Monday, June 30, 2008.

Research significance:

This is an independent PIT timing control for 2008. It is not itself a complete constituent list.

## 2013 — historical use of the stable Russell membership URL

Sources/leads:

- http://www.russell.com/indexes/documents/Membership/Russell3000_Membership_List.pdf
- https://wl6.wealth-lab.com/Forum/Posts/Use-Russell-3000-for-multi-symbol-backtest-33542
- https://studylib.net/doc/18717247/investment-performance-and-price
- https://investor.insmed.com/2013-06-28-Insmed-to-Join-the-Russell-Global-R-and-Russell-3000-R-Indexes

Observed evidence:

- A September 2013 Wealth-Lab discussion links directly to the same Russell membership PDF path as the official constituent source.
- A 2013 research paper cites the same Russell membership PDF URL and includes Russell 3000 constituent material in its appendix.
- A June 28, 2013 Insmed announcement states that 2013 Russell reconstitution occurred June 28 and that membership remains in place for one year.

Research significance:

The stable Russell PDF URL was in active public use in 2013. This strengthens the Wayback hypothesis because an overwritten stable URL is precisely where timestamped archive captures can recover historical versions.

## Evidence hierarchy for this experiment

Preferred order:

1. Original Russell/FTSE Russell full membership artifact preserved contemporaneously or in Wayback.
2. Contemporaneous authoritative additions/deletions plus an accepted prior universe.
3. Independent contemporaneous exchange notices/company announcements for publication/effective-date corroboration.
4. Preserved mirrors used only with content corroboration.
5. Current/future information is never used to infer historical membership.

## Important boundary

Russell eligibility can replace historical share-class/category eligibility only if the strategy contract is explicitly changed to make Russell 3000 membership the authoritative investable-universe overlay.

It does **not** by itself solve:

- ticker reuse/security identity;
- missing observed open/close/volume;
- split/dividend correctness;
- exact terminal economics;
- SPY/BIL data dependencies;
- PIT timing of the annual universe itself.

Those remain separately auditable contracts.
