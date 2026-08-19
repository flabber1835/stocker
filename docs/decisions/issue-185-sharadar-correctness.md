# Issue 185: Sharadar correctness decision

Status: accepted for `codex/issue-185-sharadar-correctness`.

## Scope and sequencing

Sharadar economic and operational correctness is the acceptance criterion for this branch. Certification-chain reruns and certificate-output regeneration are deliberately deferred; they must not block repairing the data path. Issue #185 must not be closed as fully complete until its separately tracked certification work is eventually finished.

## Economic domain

Sharadar SEP `close` is split-adjusted, `closeunadj` is raw/as-traded, and `volume` is split-adjusted. Liquidity must never multiply values from different split domains.

At the provider boundary, derive a raw-compatible liquidity volume:

```
raw_volume = reported_volume * adjusted_close / raw_close
```

for positive finite inputs. The invariant is:

```
raw_close * raw_volume == adjusted_close * reported_volume
```

within floating-point tolerance. Non-split rows (`adjusted_close == raw_close`) are unchanged.

The canonical `VendorBar.volume`, `sentinel_bars.volume`, and newly ingested `bt_prices.volume` domain is raw/as-traded-compatible shares, because Wealth Core liquidity is expressed as `raw_close * volume`. Sharadar's reported split-adjusted volume is used only at the source boundary to derive this canonical value and to establish that a market print existed.

Sharadar ACTIONS dividend `value` is also stated on the vendor's current split-adjusted share basis. Wealth Core's durable holdings and dividend ledger own the number of shares that actually existed on the historical ex-date. Therefore a positive ACTIONS dividend must cross the same split-domain boundary on its effective SEP row:

```
raw_dividend_per_share = ACTIONS.value * closeunadj / close
```

The cash-entitlement invariant is that a later split may change the historical share count and the vendor's stated per-share amount, but it must not change the dollars owed to the holder. Example: an AAPL ACTIONS value of `0.1175` on a row where `closeunadj / close == 4` is `$0.47` per then-outstanding historical share. The same rule spans multiple later splits; a factor of 28 maps `0.1175` to `$3.29`.

A positive dividend with no usable adjusted/raw price pair fails closed rather than guessing a share basis. Zero remains the explicit no-distribution value. The conversion happens exactly once at the SEP-to-`VendorBar` boundary in both Sentinel ingest and the canonical backtester. The engine's established same-session order remains split first, dividend second, so post-split shares receive the post-split per-share amount without double adjustment.

A corpus created with the previous volume or dividend semantics is not migrated by interpretation. Sentinel must be completely re-seeded with the corrected build, and the historical bt-data price stage must be re-backfilled before its liquidity/backtest results are trusted. Historical performance evidence that applied ACTIONS dividend values directly to raw historical share counts is superseded and must be rerun before it is used as a financial claim.

## Corrections and mutation state

A market-session frontier and a vendor mutation frontier are different authorities.

- The daily session overlap still begins fourteen calendar days behind the **published/visible** market frontier.
- SEP current-source mutations are additionally queried by an inclusive `lastupdated.gte` watermark. Equal-watermark rows are replayed idempotently so multiple changes sharing one vendor date cannot be skipped.
- The mutation watermark lives inside corpus-publication evidence. A failed or success-but-unpublished ingest therefore cannot advance the cursor used by the next run.
- A historical mutation outside the ordinary overlap triggers a complete, source-stable refetch of its affected calendar year.
- One closed historical SEP year is completely reconciled per successful daily run. Current source keys are compared with the prior published source projection before that year's candidate bars are written; an upstream removal is a typed fail-closed condition rather than an in-place deletion of published history.
- ACTIONS has no equivalent mutation timestamp, so the complete corpus-history ACTIONS window is reconciled at least weekly through the existing generation lifecycle.

A legacy published corpus with no durable SEP mutation watermark is refused for daily operation. The supported migration is the complete corrected re-seed above; choosing a guessed watermark could permanently skip an older vendor correction.

## Candidate and restart authority

Physical presence is not publication authority.

- Daily retries start from the latest **visible** session, never a farther `MAX(session)` left by an unpublished candidate.
- Split-predecessor lookup admits only already-published rows plus rows written by the current candidate. A failed candidate cannot seed a replacement run's split inference.
- A validated daily run that crashed after durable success but before publication may be published exactly if the existing publication coherence guards still prove it self-contained. Otherwise the replacement daily run completely supersedes it.
- A seed crash is recovered by a complete seed retry. This is intentionally more work: the current build rewrites TICKERS, ACTIONS, SPY and every SEP year before the replacement generation can publish, so the migration to corrected volume semantics cannot depend on pre-fix candidate state.
- Publication failure is no longer swallowed by the public ingest path. A candidate can be durably valid and pending publication, but the command must not report successful operation while the published authority remains behind it.

## Protocol behavior

The current production transport is explicitly the Nasdaq Data Link Tables v3 adapter for Sharadar. A future Sharadar direct-API integration is a different protocol adapter, not a base-URL substitution.

A successful HTTP response is not a successful Sharadar response unless it has a valid datatable envelope, nonempty unique column names, required consumer columns, exact row widths, a valid `meta.next_cursor_id` field, and one schema for the entire cursor traversal. Cursor repetition, impossible cursor types/lengths and page-cap exhaustion fail closed.

Authentication and cursor parameters are transport-owned; callers cannot override them. Retries remain limited to transport failures and explicitly retryable HTTP status codes. `Retry-After` is interpreted as either delta-seconds or an HTTP date for both 429 and 503. If the provider-directed delay exceeds the configured process blocking ceiling, Sentinel defers/fails that run rather than intentionally retrying before the provider requested.

## Certification boundary

Certification reruns, golden-output replacement, certificate rotation, and strategy recertification are intentionally deferred per project direction. They remain necessary before issue #185 as a whole can be called complete, but they do not block landing the Sharadar correctness repairs.
