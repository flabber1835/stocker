# Sharadar financial-grade authority closure

**Status:** review branch follow-up to merged PR #186, 2026-08-19.

This note records the post-#186 audit findings that required additional source
authority. It does not change Wealth Core or Sentinel strategy rules.

## Economic domains

The corrected liquidity contract remains:

```text
raw_compatible_volume = SEP.volume * SEP.close / SEP.closeunadj
SEP.closeunadj * raw_compatible_volume == SEP.close * SEP.volume
```

`sentinel_bars.volume` and post-fix `bt_prices.volume` therefore store the
raw/as-traded-compatible quantity consumed with the raw close, not the verbatim
Sharadar source volume.

The corrected dividend contract remains:

```text
raw_dividend_per_share = ACTIONS.value * SEP.closeunadj / SEP.close
```

A positive dividend without both price domains fails closed.

## Whole-export negative-space authority

Two identical cursor-paginated reads prove stability, not completeness. The same
prematurely terminal response could repeat. Nasdaq Data Link's documented Table
Exporter provides a stronger witness for the cases where absence itself changes
economics: a generated zipped CSV plus `file.status`,
`file.data_snapshot_time`, and `datatable.last_refreshed_time`.

Sentinel accepts an export only when it is `Fresh` and its snapshot creation time
is at or after the table's latest refresh. Credential-bearing download URLs are
transport-only and are not persisted or rendered.

Official provider reference:

- https://docs.data.nasdaq.com/docs/in-depth-usage-1

## TICKERS and daily SEP

TICKERS field values remain on strict paginated JSON because source NULL and an
observed blank `relatedtickers` carry different semantics. The fresh whole-table
export is used only as an independent `table=SEP` `(permaticker,ticker)` key-set
witness; the paginated and exported key sets must match exactly.

For every newly exposed SEP session, those same stable TICKERS listing intervals
predict the expected priced ticker population. Observed SEP coverage must be at
least 99.9%. Retained 2026 calibration found the worst legitimate coverage at
about 99.9518%; the large 2026-07-31 to 2026-08-03 population contraction was
fully explained by TICKERS listing ends.

This makes the older 80% recent-population readiness threshold an anomaly check,
not publication-completeness authority.

## ACTIONS

A missing ACTIONS row can erase a split, dividend, or terminal event. Production
complete reconciliation therefore uses a fresh whole-table export over the
explicit `1900-01-01..decision-frontier` window. The stronger durable cursor is:

```text
sharadar-actions-export-reconcile:v2
```

A legacy v1 cursor cannot satisfy v2 readiness. The default complete-export
cadence is one decision day. Split/dividend changes re-normalize the affected SEP
windows against the candidate action generation before one publication activates
both action and bar economics.

## Historical TICKERS identity correction

`sentinel_bars` is keyed by `(security_id,session)`. Publishing only a corrected
TICKERS interval can leave an old historical bar key visible under a resolver
that no longer names it. A complete TICKERS candidate is therefore refused if it
changes, introduces, or omits a listing interval overlapping already-published
SEP history.

Forward-only daily interval extension and genuinely new post-frontier listings
remain allowed. A real historical identity correction needs a complete
identity-aware rebuild capable of re-keying/tombstoning affected bars atomically;
the runtime does not guess that repair.

## Recent SEP deletion/key proof

`lastupdated` finds changed/inserted SEP rows but cannot reveal a row that vanished.
The rotating annual audit remains useful for deep history, but the current Wealth
Core signal window receives an additional proof every daily cycle.

After ordinary daily publication, SEP mutation CDC, and complete ACTIONS
reconciliation all finish, Sentinel exports and canonically reconciles the exact
`REQUIRED_CLOSES` decision-history window. It compares:

1. normalized `(security_id,session,ticker)` membership; and
2. exact persisted signal close, raw close, raw open, and volume.

The dedicated recent-proof cursor names both the decision frontier and the exact
current corpus publication version. Readiness fails if the proof is missing,
behind, or belongs to an older publication. Any later mutation publication thus
invalidates an earlier negative-space proof automatically.

## Existing bt_prices migration

A pre-#185 `bt_prices.volume` column contains the old split-adjusted source
quantity, while new rows contain raw-compatible volume. Numeric values cannot
identify which semantic epoch produced an existing row.

The schema therefore adds a nullable `volume_domain_version` with **no default**.
Only post-fix price writes are trigger-stamped:

```text
sharadar-raw-volume-v1
```

A partial index contains every unmarked/unknown row. The bt-engine's READY
generation gate checks that index before its first price query and refuses the
corpus if even one old row remains. This is an explicit gate rather than row-level
security because the existing backtest PostgreSQL bootstrap role is a superuser
and could bypass RLS.

The supported one-time repair is the resumable command inside the post-fix
bt-data image:

```text
python -m app.volume_domain_migration
```

It owns the normal corpus writer lock, resumes only its own interrupted migration,
force-replays the complete stored SEP date range, refreshes configured benchmark
prices, proves every row has the new semantic marker, and only then publishes a
new READY data UUID. An old row absent from current source is not deleted or
blindly grandfathered; it remains a blocker requiring investigation.

`bt-engine` also waits for bt-data health, closing the startup race where an
engine could otherwise begin reading before the semantic schema guard existed.

## Final authority shape

```text
strict transport/protocol
    -> TICKERS whole-export identity-key witness
    -> repeated cross-table source stability
    -> SEP listing-population completeness
    -> canonical economic normalization
    -> durable candidate + publication
    -> SEP lastupdated CDC
    -> ACTIONS daily whole-export reconciliation
    -> recent SEP whole-export key/value reconciliation
    -> readiness bound to exact final corpus version
```

This proves consistency with the current Sharadar reconstruction. It does not
recreate historical vendor vintages that were never retained and does not alter
the separately documented point-in-time SEC/certification limitations.
