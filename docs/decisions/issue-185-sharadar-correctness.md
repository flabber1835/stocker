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

The canonical `VendorBar.volume` and persisted `sentinel_bars.volume` domain is raw/as-traded-compatible shares, because Wealth Core liquidity is expressed as `raw_close * volume`. Sharadar's reported split-adjusted volume is used at the source boundary when deriving this value and when determining source tradeability; downstream code must not silently reinterpret it as raw volume.

## Corrections and overlap

The daily feed already re-fetches a fourteen-calendar-day SEP overlap, exceeding the issue's minimum recent-session rescan requirement. Material payload differences are upserted. This branch will preserve Sharadar correction metadata where practical and will not reduce that overlap.

## Protocol behavior

A successful HTTP response is not a successful Sharadar response unless it has a valid datatable envelope, well-formed column descriptors, and rows whose widths match the schema. Malformed successful responses are protocol failures and are not retried as transport failures. Retries remain limited to transport failures and explicitly retryable HTTP status codes.

## Crash/certification boundaries

Crash-convergence improvements that are independent of Sharadar semantic correctness may be handled separately inside #185. Certification reruns, golden-output replacement, and certificate rotation are intentionally out of scope for this branch per project direction.